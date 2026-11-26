"""Domain model for M&A tenant onboarding.

Vocabulary
----------
Tier   - HOW an acquired company is isolated inside the parent's platform.
         SILO   : dedicated cloud account / VPC / database / KMS key. Max isolation, max cost.
         BRIDGE : dedicated schema + dedicated KMS key on the shared control plane,
                  identity federated (not merged). The "interstate highway with tolls".
         POOL   : shared database, row-level isolation by tenant_id. Cheapest, fully absorbed.
Phase  - WHERE the deal is on the integration timeline. Each phase has hard gates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    SILO = "silo"
    BRIDGE = "bridge"
    POOL = "pool"

    @property
    def isolation_rank(self) -> int:
        return {"silo": 3, "bridge": 2, "pool": 1}[self.value]


class Phase(str, Enum):
    PRE_CLOSE = "pre_close"      # signed, not closed: clean-team only (antitrust gun-jumping rules)
    DAY_1 = "day_1"              # legal close: isolate, federate identity, consolidate financials read-only
    DAY_100 = "day_100"          # stabilise: SoD clean, shared services migrating, TSAs being exited
    DAY_365 = "day_365"          # converge to target tier
    INTEGRATED = "integrated"    # target state reached, TSAs exited
    CARVED_OUT = "carved_out"    # divested / unwound

    @classmethod
    def order(cls) -> list["Phase"]:
        return [cls.PRE_CLOSE, cls.DAY_1, cls.DAY_100, cls.DAY_365, cls.INTEGRATED]

    def next(self) -> "Phase | None":
        seq = Phase.order()
        if self not in seq:
            return None
        i = seq.index(self)
        return seq[i + 1] if i + 1 < len(seq) else None

    def at_least(self, other: "Phase") -> bool:
        seq = Phase.order()
        if self not in seq or other not in seq:
            return False
        return seq.index(self) >= seq.index(other)


class Intent(str, Enum):
    ABSORB = "absorb"              # fold fully into parent (e.g. tuck-in SaaS)
    PRESERVE = "preserve"          # keep brand/ops standalone (holding-company model)
    DIVEST_LIKELY = "divest_likely"  # regulator remedy or non-core: keep carve-out-ready


@dataclass
class TSAService:
    name: str
    provider: str            # usually the seller
    monthly_cost: float
    end_date: str            # ISO date
    exit_plan: str | None = None


@dataclass
class DealManifest:
    """Everything the integration management office (IMO) knows about the target."""
    deal_id: str
    target_name: str
    parent_tenant: str
    intent: Intent
    closed: bool
    regulatory_regimes: list[str]          # e.g. ["SOX","GLBA","PCI-DSS","GDPR","FedRAMP-High"]
    data_residency: list[str]              # regions where target data must stay, e.g. ["eu-west-1"]
    parent_regions: list[str]
    headcount: int
    applications: int
    critical_security_findings: int
    identity_provider: str                 # e.g. "okta", "azure-ad", "on-prem-ad"
    mfa_coverage_pct: float
    pending_regulatory_approval: bool
    clean_team: list[str] = field(default_factory=list)
    group_mappings: dict[str, list[str]] = field(default_factory=dict)  # acquired group -> parent roles
    acquired_groups: dict[str, list[str]] = field(default_factory=dict)  # group -> members
    tsa: list[TSAService] = field(default_factory=list)
    monthly_usage: dict[str, float] = field(default_factory=dict)  # resource -> units

    @classmethod
    def from_dict(cls, d: dict) -> "DealManifest":
        d = dict(d)
        d["intent"] = Intent(d["intent"])
        d["tsa"] = [TSAService(**t) for t in d.get("tsa", [])]
        return cls(**d)


@dataclass
class Tenant:
    tenant_id: str
    name: str
    parent_id: str | None
    tier: Tier
    target_tier: Tier
    phase: Phase
    regions: list[str]
    regimes: list[str]
    deal_id: str | None = None
    attributes: dict = field(default_factory=dict)
