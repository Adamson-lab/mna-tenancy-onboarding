"""Identity federation for acquired workforces.

Day-1 reality: the target runs its own IdP (Okta / Entra ID / on-prem AD). We do NOT
merge directories on Day 1. We FEDERATE: acquired groups are mapped to parent roles
*scoped to the acquired tenant*, and every mapping is checked for:

  * unmapped groups          -> users who silently lose (or keep!) access
  * Segregation-of-Duties    -> toxic role combinations that only appear after merging
  * privileged sprawl        -> admin roles that need re-certification on Day 1
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import DealManifest

# Parent company's role catalogue (would come from IGA: SailPoint / Saviynt / Entra).
ROLE_CATALOG: dict[str, dict] = {
    "employee":            {"privileged": False},
    "finance_viewer":      {"privileged": False},
    "finance_analyst":     {"privileged": False},
    "gl_close":            {"privileged": True},
    "payments_initiate":   {"privileged": True},
    "payments_approve":    {"privileged": True},
    "vendor_master_edit":  {"privileged": True},
    "hr_viewer":           {"privileged": False},
    "hr_admin":            {"privileged": True},
    "cloud_admin":         {"privileged": True},
    "security_admin":      {"privileged": True},
    "customer_data_read":  {"privileged": False},
    "customer_pii_read":   {"privileged": True},
    "clean_team":          {"privileged": False},
    "auditor_readonly":    {"privileged": False},
}

# Toxic combinations (SOX / COSO). Holding both = fraud path.
SOD_RULES: list[tuple[str, str, str]] = [
    ("payments_initiate", "payments_approve", "Initiate and approve own payments"),
    ("vendor_master_edit", "payments_approve", "Create a vendor and pay it"),
    ("gl_close", "payments_initiate", "Move money and close the books"),
    ("security_admin", "auditor_readonly", "Administer controls you audit"),
]


@dataclass
class IdentityReport:
    tenant_id: str
    users: int
    mapped_groups: int
    unmapped_groups: list[str] = field(default_factory=list)
    unknown_roles: list[str] = field(default_factory=list)
    sod_conflicts: list[dict] = field(default_factory=list)
    privileged_users: list[str] = field(default_factory=list)
    mfa_coverage_pct: float = 0.0

    @property
    def critical(self) -> list[str]:
        out = []
        if self.unknown_roles:
            out.append(f"mappings reference unknown roles {self.unknown_roles}")
        if self.sod_conflicts:
            out.append(f"{len(self.sod_conflicts)} SoD conflict(s)")
        if self.mfa_coverage_pct < 60:
            out.append(f"MFA coverage {self.mfa_coverage_pct:.0f}% < 60%")
        return out

    def to_dict(self) -> dict:
        return {**self.__dict__, "critical": self.critical}


def user_roles(m: DealManifest) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = {}
    for group, members in m.acquired_groups.items():
        for u in members:
            roles.setdefault(u, set()).update(m.group_mappings.get(group, []))
    for u in m.clean_team:
        if ":" not in u:  # target-side clean-team member (parent-side ones are "parent:user")
            roles.setdefault(u, set()).add("clean_team")
    return roles


def analyse(m: DealManifest, tenant_id: str) -> IdentityReport:
    roles = user_roles(m)
    unmapped = sorted(g for g in m.acquired_groups if g not in m.group_mappings)
    unknown = sorted({r for rs in m.group_mappings.values() for r in rs if r not in ROLE_CATALOG})
    conflicts = []
    for u, rs in sorted(roles.items()):
        for a, b, why in SOD_RULES:
            if a in rs and b in rs:
                conflicts.append({"user": u, "roles": [a, b], "risk": why})
    priv = sorted(u for u, rs in roles.items() if any(ROLE_CATALOG.get(r, {}).get("privileged") for r in rs))
    return IdentityReport(tenant_id, len(roles), len(m.acquired_groups) - len(unmapped), unmapped, unknown,
                          conflicts, priv, m.mfa_coverage_pct)


def apply_federation(store, m: DealManifest, tenant_id: str, *, quarantine_sod: bool = True) -> dict:
    """Create principals + tenant-scoped grants. SoD-conflicted roles are withheld (quarantined)."""
    report = analyse(m, tenant_id)
    # Withhold the *approval/second* side of each toxic pair; the user keeps their day job.
    blocked = {(c["user"], c["roles"][1]) for c in report.sod_conflicts} if quarantine_sod else set()
    granted = withheld = 0
    for u, rs in user_roles(m).items():
        pid = f"{tenant_id}:{u}"
        store.put_principal(pid, tenant_id, {"idp": m.identity_provider, "clean_team": u in m.clean_team})
        for r in sorted(rs):
            if r not in ROLE_CATALOG:
                continue
            if (u, r) in blocked:
                withheld += 1
                continue
            store.grant(pid, tenant_id, r, source=f"federation:{m.identity_provider}")
            granted += 1
    # Clean-team members from the PARENT get a clean_team grant on the target.
    for u in m.clean_team:
        if ":" in u:  # parent-qualified e.g. "acme:cfo"
            store.put_principal(u, u.split(":")[0], {"clean_team": True})
            store.grant(u, tenant_id, "clean_team", source="clean-team-roster")
    return {"granted": granted, "withheld_for_sod": withheld, "report": report.to_dict()}
