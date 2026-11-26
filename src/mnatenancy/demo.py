"""Scripted end-to-end walkthrough: one parent, four acquisitions, every control exercised.

    python -m mnatenancy demo            # prints the story, leaves demo.db + out/
    python -m mnatenancy demo --serve    # ...then opens the live dashboard on :8080
"""
from __future__ import annotations

import os
import shutil
import sqlite3

from .service import Platform
from .store import Store

DEALS = os.environ.get("MNAT_DEALS", "deals")
G, U, F, S = ("northwind-globex-bank", "northwind-umbrella-federal-systems",
              "northwind-initech-cloud", "northwind-sahel-pay")


def h(title: str) -> None:
    print(f"\n\033[1m━━ {title} {'━' * max(2, 76 - len(title))}\033[0m")


def az(p: Platform, who, action, tenant, **ctx) -> dict:
    d = p.authorize(who, action, tenant, ctx)
    mark = "\033[32mALLOW\033[0m" if d["allow"] else "\033[31mDENY \033[0m"
    extra = f" ctx={ctx}" if ctx else ""
    print(f"  {mark} [{d['rule']}] {who:<34} {action:<27} on {tenant}{extra}\n         └─ {d['reason']}")
    return d


def gates(p: Platform, tid: str) -> dict:
    from .phases import gate_checks
    g = gate_checks(p.store, tid)
    state = "\033[32mREADY\033[0m" if g["ready"] else "\033[31mBLOCKED\033[0m"
    print(f"  {tid}: {g['phase']} → {g['next']}  {state}")
    for f in g["failures"]:
        print(f"     ✗ {f}")
    return g


def adv(p: Platform, tid: str) -> dict:
    r = p.advance(tid, "imo-lead")
    if r["advanced"]:
        mig = f"  (tier migrated → {r['tier'].upper()})" if r["tier_migrated"] else ""
        print(f"  ✓ {tid} advanced to {r['phase']}{mig}")
    else:
        print(f"  ✗ {tid} blocked: {r['failures']}")
    return r


def run(db: str = "demo.db", out: str = "out", serve_after: bool = False, port: int = 8080) -> int:
    for path in (db, out):
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    p = Platform(db, out)

    h("1. Bootstrap the acquirer (parent tenant + its IGA roles)")
    print(" ", p.bootstrap_parent(f"{DEALS}/parent-northwind.json"))

    h("2. Onboard four deals - the tiering engine decides isolation per deal")
    print(f"  {'target':<26}{'risk':>5}  {'day-1':<8}{'target':<8} hard constraints")
    for f in ("globex-bank", "initech-cloud", "umbrella-federal", "sahel-pay"):
        r = p.onboard(f"{DEALS}/{f}.json")
        d = r["decision"]
        print(f"  {r['tenant_id'].removeprefix('northwind-'):<26}{d['risk_score']:>5}  {d['day1_tier']:<8}"
              f"{d['target_tier']:<8} {'; '.join(d['hard_constraints']) or '-'}")
        idr = r["identity"]
        if idr["withheld_for_sod"]:
            print(f"  {'':<26}  ↳ identity: {idr['granted']} grants, {idr['withheld_for_sod']} QUARANTINED for SoD "
                  f"{[c['user'] for c in idr['report']['sod_conflicts']]}")
    print(f"  landing-zone tfvars rendered → {out}/terraform/")

    h("3. PRE-CLOSE: gun-jumping guard (HSR Act / EU Merger Regulation)")
    az(p, "northwind:cro", "read_aggregated_financials", G)
    az(p, "northwind:corpdev", "read_aggregated_financials", G)
    az(p, "northwind:corpdev", "read_customer_pii", G)

    h("4. Globex Bank closes → Day 1")
    gates(p, G)
    p.remediate(G, "closed", True)
    print("  · legal confirms close")
    adv(p, G)

    h("5. Day 1 → Day 100 gate: SoD, MFA, open criticals")
    p.store.grant(f"{G}:chen", G, "payments_approve", source="emergency-ticket-INC-4471")
    print("  · treasury escalates: someone re-grants chen payments_approve via an emergency ticket")
    gates(p, G)
    p.resolve_sod(G, f"{G}:chen", "payments_approve")
    p.remediate(G, "mfa_coverage_pct", 94)
    p.remediate(G, "critical_security_findings", 0)
    print("  · IGA removes toxic combo, MFA rollout hits 94%, 2 criticals closed")
    gates(p, G)
    adv(p, G)

    h("6. BRIDGE tier: consolidation allowed, operational access is not")
    az(p, "northwind:cfo", "read_aggregated_financials", G)
    az(p, "northwind:cro", "read_customer_data", G)
    az(p, f"{G}:ines", "read_customer_pii", G, region="us-east-1")
    az(p, f"{G}:ines", "read_customer_pii", G, region="eu-west-1")
    az(p, f"{G}:amara", "approve_payment", G)

    h("7. Initech Cloud: low-risk tuck-in races to POOL")
    adv(p, F)
    adv(p, F)
    adv(p, F)

    h("8. Pooled data plane: tenant-scoped repository (no cross-tenant reads, by construction)")
    for who in (f"{G}:ines", "northwind:cro", f"{F}:nia"):
        r = p.records(who)
        print(f"  {who:<34} scope={r['scope']} rows={r.get('count', 0)}")
    print("  ↳ CRO inherits into POOLED Initech (Day 365) but NOT into BRIDGED Globex")

    h("9. Umbrella Federal (FedRAMP-High / ITAR): SILO forever")
    adv(p, U)
    az(p, "northwind:platform-lead", "admin_infrastructure", U)
    az(p, "northwind:fed-lead", "read_customer_data", U)
    az(p, "northwind:ciso", "admin_infrastructure", U, break_glass=True,
       justification="SEV1 INC-9001 ransomware containment on UFS bastion")

    h("10. Sahel Pay: regulator approval pending - stays in clean room")
    gates(p, S)
    az(p, "northwind:corpdev", "read_aggregated_financials", S)
    az(p, "northwind:cfo", "read_aggregated_financials", S)

    h("11. CFO view: TSA exposure and synergy case")
    pf = p.portfolio()
    for t in pf["tenants"]:
        print(f"  {t['name']:<26} {t['tier']:>6} → {t['target_tier']:<6} ${t['monthly_cost']:>12,.0f}/mo   "
              f"synergy ${t['annualised_synergy']:>13,.0f}/yr")
    print(f"  {'PORTFOLIO':<26} TSA run-rate ${pf['monthly_tsa_run_rate']:,.0f}/mo · "
          f"annualised synergy ${pf['annualised_synergy']:,.0f} · TSAs RED: {pf['tsa']['red']}")

    h("12. Regulator orders divestiture of Umbrella Federal → carve-out")
    m = p.carve_out(U)
    print(f"  exported {m['records_exported']} records (sha256 {m['export_sha256'][:16]}…), "
          f"purged {m['records_purged']}, residual {m['residual_records']}, grants revoked {m['grants_revoked']}, "
          f"clean={m['clean']}")
    az(p, f"{U}:pat", "read_customer_data", U)

    h("13. Tamper-evidence: someone edits the audit log directly")
    tampered = db + ".tampered"
    shutil.copy(db, tampered)
    con = sqlite3.connect(tampered)
    con.execute("UPDATE audit SET detail='{\"allow\": true}' WHERE seq = (SELECT MIN(seq) FROM audit "
                "WHERE action LIKE 'authz:%' AND detail LIKE '%\"allow\": false%')")
    con.commit(); con.close()
    print("  original :", p.store.verify_audit())
    print("  tampered :", Store(tampered).verify_audit())
    os.remove(tampered)

    print(f"\nDone. State in {db}; tfvars + carve-out evidence in {out}/. "
          f"Run `python -m mnatenancy --db {db} serve` for the dashboard.")
    if serve_after:
        from .api import serve
        serve(p, port=port)
    return 0
