"""The CFO view: TSA exposure, chargeback, and the synergy case for converging tiers.

Unit rates are illustrative list-price-ish numbers; replace with your FinOps rate card
(rates/ratecard.json is loaded if present).
"""
from __future__ import annotations

import json
import os
from datetime import date

from .models import Tier

DEFAULT_RATECARD = {
    # fixed monthly platform overhead per tenant (accounts, VPCs, KMS, SIEM, on-call, audits)
    "fixed": {"silo": 42000.0, "bridge": 11000.0, "pool": 1500.0},
    # per-unit monthly rate multipliers by tier (shared infra is cheaper per unit)
    "multiplier": {"silo": 1.35, "bridge": 1.10, "pool": 1.00},
    "unit": {"vcpu": 28.0, "storage_tb": 23.0, "db_tb": 210.0, "seats": 9.0, "egress_tb": 85.0},
}


def ratecard() -> dict:
    path = os.environ.get("MNAT_RATECARD", "rates/ratecard.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return DEFAULT_RATECARD


def monthly_cost(usage: dict[str, float], tier: Tier, rc: dict | None = None) -> float:
    rc = rc or ratecard()
    variable = sum(rc["unit"].get(k, 0.0) * v for k, v in usage.items())
    return round(rc["fixed"][tier.value] + variable * rc["multiplier"][tier.value], 2)


def chargeback(store, tenant_id: str) -> dict:
    t = store.get_tenant(tenant_id)
    usage = store.usage(tenant_id)
    current = monthly_cost(usage, t.tier)
    target = monthly_cost(usage, t.target_tier)
    tsa_run = sum(s["monthly_cost"] or 0 for s in store.list_tsa(tenant_id)
                  if date.fromisoformat(s["end_date"]) >= date.today())
    return {
        "tenant_id": tenant_id,
        "tier": t.tier.value,
        "target_tier": t.target_tier.value,
        "monthly_platform_cost": current,
        "monthly_cost_at_target": target,
        "monthly_tsa_run_rate": round(tsa_run, 2),
        "annualised_synergy": round((current - target) * 12 + tsa_run * 12, 2),
        "by_tier": {x.value: monthly_cost(usage, x) for x in Tier},
    }


def tsa_exposure(store, horizon_days: int = 90, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    rows = []
    for s in store.list_tsa():
        days = (date.fromisoformat(s["end_date"]) - as_of).days
        status = ("EXPIRED" if days < 0 else "RED" if days <= horizon_days and not s["exit_plan"]
                  else "AMBER" if days <= horizon_days else "GREEN")
        rows.append({**s, "days_left": days, "status": status})
    return {
        "as_of": as_of.isoformat(),
        "horizon_days": horizon_days,
        "services": rows,
        "red": sum(r["status"] == "RED" for r in rows),
        "monthly_run_rate": round(sum(r["monthly_cost"] or 0 for r in rows if r["days_left"] >= 0), 2),
    }
