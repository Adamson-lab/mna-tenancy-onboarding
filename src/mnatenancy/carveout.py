"""Divestiture / carve-out: the reverse path regulators increasingly force (remedies,
consent decrees) and boards increasingly choose (conglomerate break-ups).

The test of a good tenancy model is not how fast you absorb a company - it is whether
you can hand it back, cleanly, with evidence, in a weekend.
"""
from __future__ import annotations

import hashlib
import json
import os

from .models import Phase
from .store import TenantScopedRepo


def carve_out(store, tenant_id: str, actor: str, out_dir: str = "out/carveouts") -> dict:
    t = store.get_tenant(tenant_id)
    if t is None:
        raise KeyError(tenant_id)
    if t.phase is Phase.CARVED_OUT:
        raise ValueError(f"{tenant_id} already carved out")

    repo = TenantScopedRepo(store, {tenant_id})
    records = repo.query()
    os.makedirs(out_dir, exist_ok=True)
    data_path = os.path.join(out_dir, f"{tenant_id}.records.jsonl")
    with open(data_path, "w") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    digest = hashlib.sha256(open(data_path, "rb").read()).hexdigest()

    purged = repo.purge(tenant_id)
    residual = repo.count(tenant_id)
    revoked = store.revoke_tenant_grants(tenant_id)

    prior_phase = t.phase.value
    t.phase = Phase.CARVED_OUT
    store.put_tenant(t)

    manifest = {
        "tenant_id": tenant_id, "name": t.name, "tier_at_exit": t.tier.value, "phase_at_exit": prior_phase,
        "records_exported": len(records), "records_purged": purged, "residual_records": residual,
        "grants_revoked": revoked, "export_file": data_path, "export_sha256": digest,
        "tsa": store.list_tsa(tenant_id),
        "clean": residual == 0,
    }
    with open(os.path.join(out_dir, f"{tenant_id}.manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    store.audit(actor, "carveout:completed", tenant_id, manifest, severity="critical")
    return manifest
