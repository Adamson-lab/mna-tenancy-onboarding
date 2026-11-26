"""Application service layer shared by the HTTP API and the CLI."""
from __future__ import annotations

import json
import os

from . import carveout, finance, phases, playbook, policy
from .models import DealManifest
from .phases import effective_sod_conflicts
from .store import Store, TenantScopedRepo


class Platform:
    def __init__(self, db_path: str | None = None, out_dir: str | None = None):
        self.db_path = db_path or os.environ.get("MNAT_DB", "mnat.db")
        self.out_dir = out_dir or os.environ.get("MNAT_OUT", "out")
        self.store = Store(self.db_path)

    # -- commands
    def bootstrap_parent(self, spec_or_path) -> dict:
        spec = _load(spec_or_path)
        t = playbook.bootstrap_parent(self.store, spec)
        return {"tenant_id": t.tenant_id, "principals": len(spec.get("principals", []))}

    def onboard(self, manifest_or_path, actor: str = "imo") -> dict:
        m = DealManifest.from_dict(_load(manifest_or_path))
        return playbook.onboard(self.store, m, actor, self.out_dir)

    def advance(self, tenant_id: str, actor: str = "imo", force: bool = False) -> dict:
        return phases.advance(self.store, tenant_id, actor, force=force)

    def remediate(self, tenant_id: str, field: str, value, actor: str = "imo") -> dict:
        return phases.remediate(self.store, tenant_id, actor, field, value)

    def resolve_sod(self, tenant_id: str, principal: str, drop_role: str, actor: str = "iga") -> dict:
        return {"removed": phases.resolve_sod(self.store, tenant_id, principal, drop_role, actor)}

    def tsa_exit_plan(self, tenant_id: str, name: str, plan: str, actor: str = "imo") -> dict:
        phases.set_tsa_exit_plan(self.store, tenant_id, name, plan, actor)
        return {"ok": True}

    def authorize(self, principal: str, action: str, tenant_id: str, ctx: dict | None = None) -> dict:
        return policy.authorize(self.store, principal, action, tenant_id, ctx).to_dict()

    def records(self, principal: str, action: str = "read_customer_data", ctx: dict | None = None) -> dict:
        scope = policy.allowed_tenants(self.store, principal, action, ctx)
        if not scope:
            self.store.audit(principal, "records:denied", None, {"action": action}, severity="warning")
            return {"scope": [], "records": []}
        rows = TenantScopedRepo(self.store, scope).query()
        self.store.audit(principal, "records:read", None, {"scope": sorted(scope), "rows": len(rows)})
        return {"scope": sorted(scope), "count": len(rows), "records": rows[:50]}

    def carve_out(self, tenant_id: str, actor: str = "board") -> dict:
        return carveout.carve_out(self.store, tenant_id, actor, os.path.join(self.out_dir, "carveouts"))

    # -- queries
    def tenant_view(self, tenant_id: str) -> dict:
        t = self.store.get_tenant(tenant_id)
        if not t:
            raise KeyError(tenant_id)
        view = {
            "tenant": {**t.__dict__, "tier": t.tier.value, "target_tier": t.target_tier.value, "phase": t.phase.value},
        }
        if t.parent_id:
            view["gates"] = phases.gate_checks(self.store, tenant_id) if t.phase.next() else None
            view["sod_conflicts"] = effective_sod_conflicts(self.store, tenant_id)
            view["finance"] = finance.chargeback(self.store, tenant_id)
            view["tsa"] = self.store.list_tsa(tenant_id)
        return view

    def portfolio(self) -> dict:
        rows, synergy, tsa_run = [], 0.0, 0.0
        for t in self.store.list_tenants():
            if not t.parent_id:
                continue
            fin = finance.chargeback(self.store, t.tenant_id)
            g = phases.gate_checks(self.store, t.tenant_id) if t.phase.next() else {"ready": None, "failures": []}
            synergy += fin["annualised_synergy"]
            tsa_run += fin["monthly_tsa_run_rate"]
            rows.append({"tenant_id": t.tenant_id, "name": t.name, "parent": t.parent_id, "tier": t.tier.value,
                         "target_tier": t.target_tier.value, "phase": t.phase.value, "regimes": t.regimes,
                         "regions": t.regions, "risk_score": t.attributes.get("decision", {}).get("risk_score"),
                         "gate_ready": g["ready"], "blockers": g["failures"],
                         "monthly_cost": fin["monthly_platform_cost"],
                         "annualised_synergy": fin["annualised_synergy"],
                         "sod_conflicts": len(effective_sod_conflicts(self.store, t.tenant_id))})
        return {"tenants": rows, "annualised_synergy": round(synergy, 2),
                "monthly_tsa_run_rate": round(tsa_run, 2),
                "tsa": finance.tsa_exposure(self.store), "audit": self.store.verify_audit()}


def _load(x):
    if isinstance(x, dict):
        return x
    with open(x) as f:
        return json.load(f)
