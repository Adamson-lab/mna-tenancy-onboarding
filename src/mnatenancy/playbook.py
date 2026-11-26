"""Onboarding playbook: deal manifest in -> isolated, governed, auditable tenant out.

    manifest ─► tiering decision ─► tenant record ─► landing-zone tfvars ─►
    identity federation (SoD-quarantined) ─► TSA register ─► usage/chargeback ─► audit
"""
from __future__ import annotations

import json
import os
import random
import re

from . import identity, tiering
from .models import DealManifest, Phase, Tenant, Tier

TF_MODULE = {Tier.SILO: "tenant-silo", Tier.BRIDGE: "tenant-bridge", Tier.POOL: "tenant-pool"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def bootstrap_parent(store, spec: dict, actor: str = "system") -> Tenant:
    t = Tenant(spec["tenant_id"], spec["name"], None, Tier.POOL, Tier.POOL, Phase.INTEGRATED,
               spec["regions"], spec.get("regimes", []), None, {"is_parent": True})
    store.put_tenant(t)
    for p in spec.get("principals", []):
        pid = f"{t.tenant_id}:{p['user']}"
        store.put_principal(pid, t.tenant_id, p.get("attributes", {}))
        for r in p["roles"]:
            store.grant(pid, t.tenant_id, r, source="parent-iga")
    store.audit(actor, "parent:bootstrapped", t.tenant_id, {"principals": len(spec.get("principals", []))})
    return t


def render_landing_zone(t: Tenant, out_dir: str) -> str:
    """Re-rendered on every tier migration so `terraform plan` shows the move."""
    os.makedirs(out_dir, exist_ok=True)
    tfvars = {
        "tenant_id": t.tenant_id,
        "tenant_name": t.name,
        "parent_tenant": t.parent_id,
        "module": TF_MODULE[t.tier],
        "tier": t.tier.value,
        "target_tier": t.target_tier.value,
        "regions": t.regions,
        "regulatory_regimes": t.regimes,
        "dedicated_kms_key": t.tier is not Tier.POOL,
        "dedicated_account": t.tier is Tier.SILO,
        "network_peering_to_parent": "none" if t.tier is Tier.SILO else "transit-gateway-inspected",
        "log_archive_retention_days": 2555 if t.regimes else 365,
        "tags": {"deal_id": t.deal_id, "phase": t.phase.value, "data_owner": t.name},
    }
    path = os.path.join(out_dir, f"{t.tenant_id}.auto.tfvars.json")
    with open(path, "w") as f:
        json.dump(tfvars, f, indent=2)
    return path


def seed_synthetic_records(store, tenant_id: str, n: int = 25, seed: int = 7) -> int:
    from .store import TenantScopedRepo
    rnd = random.Random(f"{seed}:{tenant_id}")
    repo = TenantScopedRepo(store, {tenant_id})
    for i in range(n):
        repo.insert(tenant_id, "customer", {"customer_no": f"{tenant_id[:3].upper()}-{i:05d}",
                                            "balance": round(rnd.uniform(100, 250000), 2),
                                            "segment": rnd.choice(["retail", "commercial", "public"])},
                    classification="pii")
    return n


def onboard(store, manifest: DealManifest, actor: str = "imo", out_dir: str = "out",
            seed_records: int = 25) -> dict:
    tenant_id = f"{manifest.parent_tenant}-{slug(manifest.target_name)}"
    if store.get_tenant(manifest.parent_tenant) is None:
        raise ValueError(f"parent tenant {manifest.parent_tenant} not bootstrapped")
    if store.get_tenant(tenant_id) is not None:
        raise ValueError(f"tenant {tenant_id} already exists")

    decision = tiering.decide(manifest)
    id_report = identity.analyse(manifest, tenant_id)
    t = Tenant(
        tenant_id, manifest.target_name, manifest.parent_tenant, decision.day1_tier, decision.target_tier,
        Phase.PRE_CLOSE, manifest.data_residency or manifest.parent_regions, manifest.regulatory_regimes,
        manifest.deal_id,
        {
            "intent": manifest.intent.value, "closed": manifest.closed,
            "pending_regulatory_approval": manifest.pending_regulatory_approval,
            "mfa_coverage_pct": manifest.mfa_coverage_pct,
            "critical_security_findings": manifest.critical_security_findings,
            "headcount": manifest.headcount, "applications": manifest.applications,
            "identity_provider": manifest.identity_provider,
            "convergence_path": decision.convergence_path, "decision": decision.to_dict(),
            "unmapped_groups": id_report.unmapped_groups, "provisioned": False,
        },
    )
    store.put_tenant(t)
    store.audit(actor, "tenant:created", tenant_id, {"deal": manifest.deal_id, "decision": decision.to_dict()})

    tf_path = render_landing_zone(t, os.path.join(out_dir, "terraform"))
    t.attributes["provisioned"] = True
    t.attributes["landing_zone"] = tf_path
    store.put_tenant(t)
    store.audit(actor, "landing_zone:rendered", tenant_id, {"tfvars": tf_path, "module": TF_MODULE[t.tier]})

    fed = identity.apply_federation(store, manifest, tenant_id)
    store.audit(actor, "identity:federated", tenant_id,
                {"granted": fed["granted"], "withheld_for_sod": fed["withheld_for_sod"],
                 "critical": fed["report"]["critical"]},
                severity="warning" if fed["report"]["critical"] else "info")

    for s in manifest.tsa:
        store.put_tsa(tenant_id, s)
    store.put_usage(tenant_id, manifest.monthly_usage)
    if seed_records:
        seed_synthetic_records(store, tenant_id, seed_records)
    store.audit(actor, "onboarding:completed", tenant_id, {"tsa_services": len(manifest.tsa)})

    return {"tenant_id": tenant_id, "decision": decision.to_dict(), "identity": fed, "landing_zone": tf_path}


def load_manifest(path: str) -> DealManifest:
    with open(path) as f:
        return DealManifest.from_dict(json.load(f))
