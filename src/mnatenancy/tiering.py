"""Tenancy-model decision engine.

Answers the board-level question: *"For this acquisition, how isolated should it be on
Day 1, and where should it end up?"*  Decisions are explainable - every point of risk
and every hard constraint is returned as a rationale line an auditor can read.

Doctrine encoded here
---------------------
1. Hard constraints beat economics. Sovereign / defence regimes are SILO forever.
2. Isolate first, converge later. Day-1 tier is never less isolated than target tier.
3. Intent shapes the target. PRESERVE -> BRIDGE, DIVEST_LIKELY -> SILO, ABSORB -> lowest
   tier the risk score allows.
4. Data residency that the parent cannot serve in-region forces a regional SILO.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import DealManifest, Intent, Phase, Tier

SOVEREIGN_REGIMES = {"FedRAMP-High", "ITAR", "CJIS", "IL5", "NDPR-Sovereign", "CMMC-L3"}
REGIME_RISK = {
    "PCI-DSS": 2, "HIPAA": 2, "GLBA": 1, "SOX": 1, "GDPR": 1, "DORA": 2,
    "NYDFS-500": 2, "FFIEC": 1, "CBN-RiskBased": 2, "SOC2": 0,
}


@dataclass
class TieringDecision:
    day1_tier: Tier
    target_tier: Tier
    risk_score: int
    hard_constraints: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    convergence_path: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "day1_tier": self.day1_tier.value,
            "target_tier": self.target_tier.value,
            "risk_score": self.risk_score,
            "hard_constraints": self.hard_constraints,
            "rationale": self.rationale,
            "convergence_path": self.convergence_path,
        }


def score_risk(m: DealManifest) -> tuple[int, list[str]]:
    score, why = 0, []
    for r in m.regulatory_regimes:
        pts = REGIME_RISK.get(r, 0)
        if pts:
            score += pts
            why.append(f"+{pts} regime {r}")
    if m.critical_security_findings:
        pts = min(6, 2 * m.critical_security_findings)
        score += pts
        why.append(f"+{pts} {m.critical_security_findings} unresolved critical security findings")
    if m.mfa_coverage_pct < 90:
        pts = 3 if m.mfa_coverage_pct < 60 else 2
        score += pts
        why.append(f"+{pts} MFA coverage only {m.mfa_coverage_pct:.0f}%")
    if m.identity_provider == "on-prem-ad":
        score += 1
        why.append("+1 on-prem AD (no cloud-native federation)")
    if m.applications > 150:
        score += 1
        why.append(f"+1 large application estate ({m.applications} apps)")
    return score, why


def decide(m: DealManifest) -> TieringDecision:
    score, why = score_risk(m)
    hard: list[str] = []

    sovereign = sorted(SOVEREIGN_REGIMES.intersection(m.regulatory_regimes))
    if sovereign:
        hard.append(f"sovereign regime(s) {sovereign} -> dedicated SILO, never pooled")

    unserved = sorted(set(m.data_residency) - set(m.parent_regions))
    if unserved:
        hard.append(f"residency {unserved} not served by parent regions -> regional SILO until a cell exists")

    if m.pending_regulatory_approval:
        hard.append("regulatory approval pending -> no integration, clean-team access only")

    # ---- target tier --------------------------------------------------------------
    if sovereign or unserved:
        target = Tier.SILO
    elif m.intent is Intent.DIVEST_LIKELY:
        target = Tier.SILO
        why.append("intent DIVEST_LIKELY -> keep SILO so carve-out is a lift-and-shift")
    elif m.intent is Intent.PRESERVE:
        target = Tier.BRIDGE
        why.append("intent PRESERVE -> BRIDGE: shared control plane, separate brand/data plane")
    else:  # ABSORB
        target = Tier.POOL if score <= 4 else Tier.BRIDGE
        why.append(f"intent ABSORB with risk {score} -> {target.value.upper()}")

    # ---- day-1 tier: isolate first ------------------------------------------------
    if hard or score >= 5:
        day1 = Tier.SILO
    elif score >= 2:
        day1 = Tier.BRIDGE
    else:
        day1 = Tier.BRIDGE if target is Tier.POOL else target
    if day1.isolation_rank < target.isolation_rank:
        day1 = target
    why.append(f"Day-1 tier {day1.value.upper()} (isolate first, converge later)")

    path = {
        Phase.PRE_CLOSE.value: "clean-room only",
        Phase.DAY_1.value: day1.value,
        Phase.DAY_100.value: (Tier.BRIDGE if day1 is Tier.SILO and target is not Tier.SILO else day1).value,
        Phase.DAY_365.value: target.value,
        Phase.INTEGRATED.value: target.value,
    }
    return TieringDecision(day1, target, score, hard, why, path)
