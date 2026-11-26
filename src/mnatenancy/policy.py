"""Attribute-based access control across parent and acquired tenants.

Deny-overrides evaluation. Every decision - allow or deny - is written to the
hash-chained audit log with the rule that decided it. This is what you hand to the
regulator, the external auditor and the antitrust counsel.

Rules, in order
---------------
R0  tenant must exist and not be carved out
R1  PRE-CLOSE gun-jumping guard: only clean-team, only aggregated data (HSR Act / EU Merger Reg)
R2  sovereign guard: sovereign tenants require `us_person` (or local-national) attribute
R3  residency guard: customer/PII actions must originate in a permitted region
R4  break-glass: parent security_admin + justification -> allow, CRITICAL audit
R5  direct grant on the target tenant
R6  inherited grant from the parent, constrained by tier and phase:
       BRIDGE  -> only consolidation actions (finance read, audit read)
       POOL    -> full inheritance once phase >= DAY_365
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Phase, Tier
from .tiering import SOVEREIGN_REGIMES

ACTIONS: dict[str, dict] = {
    "read_aggregated_financials": {"roles": {"finance_viewer", "finance_analyst", "clean_team", "auditor_readonly",
                                             "gl_close"}, "data": "aggregated"},
    "read_customer_data":   {"roles": {"customer_data_read", "customer_pii_read"}, "data": "customer"},
    "read_customer_pii":    {"roles": {"customer_pii_read"}, "data": "pii"},
    "initiate_payment":     {"roles": {"payments_initiate"}, "data": "financial"},
    "approve_payment":      {"roles": {"payments_approve"}, "data": "financial"},
    "admin_infrastructure": {"roles": {"cloud_admin"}, "data": "infra"},
    "read_hr_records":      {"roles": {"hr_viewer", "hr_admin"}, "data": "pii"},
    "read_audit_evidence":  {"roles": {"auditor_readonly", "security_admin"}, "data": "aggregated"},
}
CONSOLIDATION_ACTIONS = {"read_aggregated_financials", "read_audit_evidence"}
RESIDENCY_SCOPED = {"customer", "pii"}


@dataclass
class Decision:
    allow: bool
    rule: str
    reason: str
    severity: str = "info"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _evaluate(store, principal_id: str, action: str, tenant_id: str, ctx: dict) -> Decision:
    spec = ACTIONS.get(action)
    if not spec:
        return Decision(False, "R0", f"unknown action {action}")
    t = store.get_tenant(tenant_id)
    if not t:
        return Decision(False, "R0", f"unknown tenant {tenant_id}")
    if t.phase is Phase.CARVED_OUT:
        return Decision(False, "R0", "tenant carved out; all access revoked", "warning")
    p = store.get_principal(principal_id)
    if not p:
        return Decision(False, "R0", f"unknown principal {principal_id}")

    grants = p["grants"]
    direct = set(grants.get(tenant_id, []))

    # R1 gun-jumping guard
    if t.phase is Phase.PRE_CLOSE:
        if "clean_team" not in direct:
            return Decision(False, "R1", "pre-close: principal not on clean-team roster (gun-jumping risk)", "warning")
        if action != "read_aggregated_financials":
            return Decision(False, "R1", "pre-close: clean team limited to aggregated, non-competitive data",
                            "warning")
        return Decision(True, "R1", "pre-close clean-team access to aggregated data")

    # R2 sovereign guard
    if SOVEREIGN_REGIMES.intersection(t.regimes) and not p["attributes"].get("us_person"):
        return Decision(False, "R2", f"sovereign tenant ({sorted(SOVEREIGN_REGIMES.intersection(t.regimes))}) "
                                     "requires us_person attribute", "warning")

    # R3 residency guard
    region = ctx.get("region")
    if spec["data"] in RESIDENCY_SCOPED and region and region not in t.regions:
        return Decision(False, "R3", f"{spec['data']} data residency {t.regions}; request from {region}", "warning")

    # R4 break-glass
    if ctx.get("break_glass"):
        parent_roles = set(grants.get(t.parent_id or "", []))
        if "security_admin" in parent_roles and len(str(ctx.get("justification", ""))) >= 15:
            return Decision(True, "R4", f"BREAK-GLASS: {ctx['justification']}", "critical")
        return Decision(False, "R4", "break-glass requires parent security_admin and a justification", "warning")

    # R5 direct grant
    if direct & spec["roles"]:
        return Decision(True, "R5", f"direct grant {sorted(direct & spec['roles'])} on {tenant_id}")

    # R6 inherited from parent
    if t.parent_id:
        inherited = set(grants.get(t.parent_id, [])) & spec["roles"]
        if inherited:
            if t.tier is Tier.SILO:
                return Decision(False, "R6", "SILO tenant: parent roles do not inherit")
            if t.tier is Tier.BRIDGE:
                if action in CONSOLIDATION_ACTIONS:
                    return Decision(True, "R6", "BRIDGE: parent role inherited for consolidation")
                return Decision(False, "R6", "BRIDGE: parent roles inherit for consolidation actions only")
            if t.tier is Tier.POOL:
                if t.phase.at_least(Phase.DAY_365) or action in CONSOLIDATION_ACTIONS:
                    return Decision(True, "R6", "POOL: parent role inherited")
                return Decision(False, "R6", "POOL: full inheritance only from DAY_365")

    return Decision(False, "R5", f"no role in {sorted(spec['roles'])} on {tenant_id}")


def authorize(store, principal_id: str, action: str, tenant_id: str, ctx: dict | None = None) -> Decision:
    ctx = ctx or {}
    d = _evaluate(store, principal_id, action, tenant_id, ctx)
    store.audit(principal_id, f"authz:{action}", tenant_id,
                {"allow": d.allow, "rule": d.rule, "reason": d.reason, "ctx": ctx},
                severity=d.severity if not d.allow or d.severity == "critical" else "info")
    return d


def allowed_tenants(store, principal_id: str, action: str, ctx: dict | None = None) -> set[str]:
    """Resolve the tenant scope for a TenantScopedRepo (without spamming the audit log)."""
    return {t.tenant_id for t in store.list_tenants()
            if _evaluate(store, principal_id, action, t.tenant_id, ctx or {}).allow}
