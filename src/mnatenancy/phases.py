"""Integration phase state machine with hard gates.

A phase cannot advance while any gate fails. Gate failures are the IMO's to-do list,
and the CEO's one-line answer to "are we ready for Day 100?".
"""
from __future__ import annotations

from datetime import date

from .identity import SOD_RULES
from .models import Phase, Tier


def effective_sod_conflicts(store, tenant_id: str) -> list[dict]:
    rows = store.db.execute("SELECT principal_id, role FROM grants WHERE tenant_id=?", (tenant_id,)).fetchall()
    by_user: dict[str, set[str]] = {}
    for r in rows:
        by_user.setdefault(r["principal_id"], set()).add(r["role"])
    out = []
    for u, rs in sorted(by_user.items()):
        for a, b, why in SOD_RULES:
            if a in rs and b in rs:
                out.append({"principal": u, "roles": [a, b], "risk": why})
    return out


def gate_checks(store, tenant_id: str, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    t = store.get_tenant(tenant_id)
    if t is None:
        raise KeyError(tenant_id)
    a = t.attributes
    nxt = t.phase.next()
    fails: list[str] = []

    if t.phase is Phase.PRE_CLOSE:
        if not a.get("closed"):
            fails.append("deal has not legally closed")
        if a.get("pending_regulatory_approval"):
            fails.append("regulatory approval still pending")
        if not a.get("provisioned"):
            fails.append("Day-1 landing zone not provisioned")
    elif t.phase is Phase.DAY_1:
        sod = effective_sod_conflicts(store, tenant_id)
        if sod:
            fails.append(f"{len(sod)} effective SoD conflict(s) in live grants")
        if a.get("mfa_coverage_pct", 0) < 90:
            fails.append(f"MFA coverage {a.get('mfa_coverage_pct', 0):.0f}% < 90%")
        if a.get("critical_security_findings", 0) > 0:
            fails.append(f"{a['critical_security_findings']} critical security findings open")
        if not store.verify_audit()["valid"]:
            fails.append("audit chain integrity failure")
    elif t.phase is Phase.DAY_100:
        missing = [s["name"] for s in store.list_tsa(tenant_id) if not s["exit_plan"]]
        if missing:
            fails.append(f"TSA services without exit plan: {missing}")
        if a.get("unmapped_groups"):
            fails.append(f"unmapped identity groups: {a['unmapped_groups']}")
    elif t.phase is Phase.DAY_365:
        live = [s["name"] for s in store.list_tsa(tenant_id) if date.fromisoformat(s["end_date"]) > as_of]
        if live:
            fails.append(f"TSAs still live as of {as_of}: {live}")
    else:
        fails.append(f"no forward transition from {t.phase.value}")

    return {"tenant_id": tenant_id, "phase": t.phase.value, "next": nxt.value if nxt else None,
            "ready": not fails, "failures": fails}


def advance(store, tenant_id: str, actor: str, as_of: date | None = None, force: bool = False) -> dict:
    g = gate_checks(store, tenant_id, as_of)
    if not g["ready"] and not force:
        store.audit(actor, "phase:blocked", tenant_id, g, severity="warning")
        return {**g, "advanced": False}
    t = store.get_tenant(tenant_id)
    old_phase, old_tier = t.phase, t.tier
    t.phase = Phase(g["next"])
    path = t.attributes.get("convergence_path", {})
    if t.phase.value in path and path[t.phase.value] in {x.value for x in Tier}:
        t.tier = Tier(path[t.phase.value])
    store.put_tenant(t)
    if old_tier is not t.tier and t.attributes.get("landing_zone"):
        import os
        from .playbook import render_landing_zone
        render_landing_zone(t, os.path.dirname(t.attributes["landing_zone"]))
    if old_phase is Phase.PRE_CLOSE:
        # Clean team dissolves at legal close; access must now come from real roles.
        with store.tx() as db:
            n = db.execute("DELETE FROM grants WHERE tenant_id=? AND role='clean_team'", (tenant_id,)).rowcount
        store.audit(actor, "clean_team:dissolved", tenant_id, {"grants_revoked": n})
    store.audit(actor, "phase:advanced", tenant_id,
                {"from": old_phase.value, "to": t.phase.value, "tier_from": old_tier.value, "tier_to": t.tier.value,
                 "forced": force and not g["ready"], "waived": g["failures"] if force else []},
                severity="critical" if force and not g["ready"] else "info")
    return {**g, "advanced": True, "phase": t.phase.value, "tier": t.tier.value,
            "tier_migrated": old_tier is not t.tier}


REMEDIABLE = {"mfa_coverage_pct": float, "critical_security_findings": int, "closed": bool,
              "pending_regulatory_approval": bool, "provisioned": bool}


def remediate(store, tenant_id: str, actor: str, field: str, value) -> dict:
    if field not in REMEDIABLE:
        raise ValueError(f"field must be one of {sorted(REMEDIABLE)}")
    caster = REMEDIABLE[field]
    if caster is bool and isinstance(value, str):
        value = value.lower() in {"1", "true", "yes"}
    value = caster(value)
    t = store.get_tenant(tenant_id)
    old = t.attributes.get(field)
    t.attributes[field] = value
    store.put_tenant(t)
    store.audit(actor, "remediate", tenant_id, {"field": field, "from": old, "to": value})
    return {"tenant_id": tenant_id, field: value}


def resolve_sod(store, tenant_id: str, principal_id: str, drop_role: str, actor: str) -> int:
    with store.tx() as db:
        n = db.execute("DELETE FROM grants WHERE principal_id=? AND tenant_id=? AND role=?",
                       (principal_id, tenant_id, drop_role)).rowcount
    store.audit(actor, "sod:resolved", tenant_id, {"principal": principal_id, "dropped": drop_role})
    return n


def set_tsa_exit_plan(store, tenant_id: str, name: str, plan: str, actor: str) -> None:
    with store.tx() as db:
        db.execute("UPDATE tsa SET exit_plan=? WHERE tenant_id=? AND name=?", (plan, tenant_id, name))
    store.audit(actor, "tsa:exit_plan", tenant_id, {"service": name, "plan": plan})
