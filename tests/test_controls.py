import os
import sqlite3

import pytest

from mnatenancy.phases import effective_sod_conflicts, gate_checks
from mnatenancy.store import CrossTenantViolation, Store, TenantScopedRepo

G, F, U, S = ("northwind-globex-bank", "northwind-initech-cloud",
              "northwind-umbrella-federal-systems", "northwind-sahel-pay")


def allow(p, who, action, tenant, **ctx):
    return p.authorize(who, action, tenant, ctx)["allow"]


# ---------------------------------------------------------------- pre-close
def test_gun_jumping_guard(onboarded):
    p = onboarded
    assert not allow(p, "northwind:cro", "read_aggregated_financials", G)
    assert allow(p, "northwind:corpdev", "read_aggregated_financials", G)
    assert not allow(p, "northwind:corpdev", "read_customer_pii", G)


def test_clean_team_dissolves_at_close(onboarded):
    p = onboarded
    p.remediate(G, "closed", True)
    assert p.advance(G)["advanced"]
    assert "clean_team" not in p.store.grants_for("northwind:corpdev").get(G, [])


def test_pending_regulatory_approval_blocks_close(onboarded):
    p = onboarded
    p.remediate(S, "closed", True)
    g = gate_checks(p.store, S)
    assert not g["ready"] and any("regulatory" in f for f in g["failures"])


# ---------------------------------------------------------------- identity / SoD
def test_sod_conflicts_quarantined_on_federation(onboarded):
    assert effective_sod_conflicts(onboarded.store, G) == []
    chen = onboarded.store.grants_for(f"{G}:chen")[G]
    assert "payments_initiate" in chen and "payments_approve" not in chen


def test_regranted_toxic_combo_blocks_day100(onboarded):
    p = onboarded
    p.remediate(G, "closed", True); p.advance(G)
    p.remediate(G, "mfa_coverage_pct", 95); p.remediate(G, "critical_security_findings", 0)
    p.store.grant(f"{G}:chen", G, "payments_approve", "emergency")
    assert not p.advance(G)["advanced"]
    p.resolve_sod(G, f"{G}:chen", "payments_approve")
    r = p.advance(G)
    assert r["advanced"] and r["tier"] == "bridge" and r["tier_migrated"]


# ---------------------------------------------------------------- policy
def _to_day100(p, t):
    p.remediate(t, "closed", True); p.advance(t)
    p.remediate(t, "mfa_coverage_pct", 95); p.remediate(t, "critical_security_findings", 0)
    assert p.advance(t)["advanced"]


def test_bridge_inherits_consolidation_only(onboarded):
    p = onboarded
    _to_day100(p, G)
    assert allow(p, "northwind:cfo", "read_aggregated_financials", G)
    assert not allow(p, "northwind:cro", "read_customer_data", G)


def test_residency(onboarded):
    p = onboarded
    _to_day100(p, G)
    assert not allow(p, f"{G}:ines", "read_customer_pii", G, region="us-east-1")
    assert allow(p, f"{G}:ines", "read_customer_pii", G, region="eu-west-1")


def test_sovereign_requires_us_person_and_silo_blocks_inheritance(onboarded):
    p = onboarded
    p.advance(U)
    assert not allow(p, "northwind:platform-lead", "admin_infrastructure", U)  # not us_person
    assert not allow(p, "northwind:fed-lead", "read_customer_data", U)  # silo, no inheritance


def test_break_glass_requires_justification_and_is_critical(onboarded):
    p = onboarded
    p.advance(U)
    assert not allow(p, "northwind:ciso", "admin_infrastructure", U, break_glass=True, justification="x")
    assert allow(p, "northwind:ciso", "admin_infrastructure", U, break_glass=True,
                 justification="SEV1 incident INC-1 containment")
    assert p.store.audit_log(U, 1)[0]["severity"] == "critical"


def test_pool_full_inheritance_only_from_day365(onboarded):
    p = onboarded
    p.advance(F); p.advance(F)  # day_100, still bridge
    assert not allow(p, "northwind:cro", "read_customer_data", F)
    p.advance(F)  # day_365 -> pool
    assert p.store.get_tenant(F).tier.value == "pool"
    assert allow(p, "northwind:cro", "read_customer_data", F)


# ---------------------------------------------------------------- data isolation
def test_scoped_repo_cannot_read_or_write_other_tenants(onboarded):
    s = onboarded.store
    repo = TenantScopedRepo(s, {G})
    assert {r["tenant_id"] for r in repo.query()} == {G}
    with pytest.raises(CrossTenantViolation):
        repo.insert(F, "customer", {"x": 1})
    with pytest.raises(CrossTenantViolation):
        repo.purge(F)
    with pytest.raises(CrossTenantViolation):
        TenantScopedRepo(s, set())


def test_records_endpoint_scopes_by_policy(onboarded):
    r = onboarded.records(f"{G}:ines", ctx={"region": "eu-west-1"})
    # Globex still PRE_CLOSE -> ines has no access yet (only clean-team)
    assert r["scope"] == []


# ---------------------------------------------------------------- audit
def test_audit_chain_detects_tampering(onboarded, tmp_path):
    p = onboarded
    p.authorize("northwind:cro", "read_customer_pii", G)
    assert p.store.verify_audit()["valid"]
    copy = tmp_path / "copy.db"
    p.store.db.execute(f"VACUUM INTO '{copy}'")
    con = sqlite3.connect(copy)
    con.execute("UPDATE audit SET actor='nobody' WHERE seq=3"); con.commit(); con.close()
    v = Store(str(copy)).verify_audit()
    assert v == {"valid": False, "entries": 3, "broken_at_seq": 3}


# ---------------------------------------------------------------- carve-out & finance
def test_carveout_is_clean_and_evidenced(onboarded):
    p = onboarded
    m = p.carve_out(U)
    assert m["clean"] and m["residual_records"] == 0 and m["records_exported"] == 25
    assert os.path.exists(m["export_file"])
    assert not allow(p, f"{U}:pat", "read_customer_data", U)
    with pytest.raises(ValueError):
        p.carve_out(U)


def test_chargeback_target_cheaper_or_equal(onboarded):
    from mnatenancy.finance import chargeback
    for t in (G, F, U, S):
        c = chargeback(onboarded.store, t)
        assert c["monthly_cost_at_target"] <= c["monthly_platform_cost"]
        assert c["by_tier"]["pool"] < c["by_tier"]["bridge"] < c["by_tier"]["silo"]


def test_landing_zone_tfvars_rendered(onboarded):
    import json
    t = onboarded.store.get_tenant(U)
    tf = json.load(open(t.attributes["landing_zone"]))
    assert tf["module"] == "tenant-silo" and tf["dedicated_account"] and tf["network_peering_to_parent"] == "none"


def test_tier_migration_rerenders_landing_zone(onboarded):
    import json
    p = onboarded
    for _ in range(3):
        p.advance(F)
    tf = json.load(open(p.store.get_tenant(F).attributes["landing_zone"]))
    assert tf["module"] == "tenant-pool" and tf["tags"]["phase"] == "day_365"
