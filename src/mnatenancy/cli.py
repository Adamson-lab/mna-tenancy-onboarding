"""`mnat` command line.

  mnat bootstrap deals/parent-northwind.json
  mnat onboard   deals/globex-bank.json
  mnat portfolio
  mnat gates     northwind-globex-bank
  mnat remediate northwind-globex-bank closed true
  mnat advance   northwind-globex-bank
  mnat authorize northwind:cro read_customer_pii northwind-globex-bank --region us-east-1
  mnat records   northwind:cro
  mnat sod-resolve northwind-globex-bank northwind-globex-bank:chen payments_approve
  mnat exit-plan northwind-globex-bank swift-gateway "Cut over to parent SWIFT Alliance Lite2"
  mnat carveout  northwind-umbrella-federal-systems
  mnat audit [--verify] [--tenant T]
  mnat serve --port 8080
  mnat demo  # end-to-end scripted walkthrough
"""
from __future__ import annotations

import argparse
import json
import sys

from .service import Platform


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mnat", description="M&A tenancy onboarding control plane")
    ap.add_argument("--db", default=None, help="SQLite path (default $MNAT_DB or mnat.db)")
    ap.add_argument("--out", default=None, help="output dir for tfvars / carve-outs")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("bootstrap").add_argument("spec")
    sub.add_parser("onboard").add_argument("manifest")
    sub.add_parser("portfolio")
    sub.add_parser("show").add_argument("tenant")
    sub.add_parser("gates").add_argument("tenant")
    s = sub.add_parser("advance"); s.add_argument("tenant"); s.add_argument("--force", action="store_true")
    s.add_argument("--actor", default="cli")
    s = sub.add_parser("remediate"); s.add_argument("tenant"); s.add_argument("field"); s.add_argument("value")
    s = sub.add_parser("authorize"); s.add_argument("principal"); s.add_argument("action"); s.add_argument("tenant")
    s.add_argument("--region"); s.add_argument("--break-glass", dest="justification")
    s = sub.add_parser("records"); s.add_argument("principal"); s.add_argument("--action", default="read_customer_data")
    s.add_argument("--region")
    s = sub.add_parser("sod-resolve"); s.add_argument("tenant"); s.add_argument("principal"); s.add_argument("drop_role")
    s = sub.add_parser("exit-plan"); s.add_argument("tenant"); s.add_argument("service"); s.add_argument("plan")
    sub.add_parser("carveout").add_argument("tenant")
    s = sub.add_parser("audit"); s.add_argument("--verify", action="store_true"); s.add_argument("--tenant")
    s.add_argument("--limit", type=int, default=30)
    s = sub.add_parser("serve"); s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8080)
    s = sub.add_parser("demo"); s.add_argument("--serve", action="store_true"); s.add_argument("--port", type=int, default=8080)

    a = ap.parse_args(argv)
    if a.cmd == "demo":
        from .demo import run
        return run(a.db or "demo.db", a.out or "out", serve_after=a.serve, port=a.port)

    p = Platform(a.db, a.out)
    if a.cmd == "bootstrap":
        _p(p.bootstrap_parent(a.spec))
    elif a.cmd == "onboard":
        _p(p.onboard(a.manifest))
    elif a.cmd == "portfolio":
        _p(p.portfolio())
    elif a.cmd == "show":
        _p(p.tenant_view(a.tenant))
    elif a.cmd == "gates":
        from .phases import gate_checks
        _p(gate_checks(p.store, a.tenant))
    elif a.cmd == "advance":
        r = p.advance(a.tenant, a.actor, a.force); _p(r)
        return 0 if r["advanced"] else 2
    elif a.cmd == "remediate":
        _p(p.remediate(a.tenant, a.field, a.value))
    elif a.cmd == "authorize":
        ctx = {}
        if a.region:
            ctx["region"] = a.region
        if a.justification:
            ctx.update(break_glass=True, justification=a.justification)
        d = p.authorize(a.principal, a.action, a.tenant, ctx); _p(d)
        return 0 if d["allow"] else 3
    elif a.cmd == "records":
        _p(p.records(a.principal, a.action, {"region": a.region} if a.region else None))
    elif a.cmd == "sod-resolve":
        _p(p.resolve_sod(a.tenant, a.principal, a.drop_role))
    elif a.cmd == "exit-plan":
        _p(p.tsa_exit_plan(a.tenant, a.service, a.plan))
    elif a.cmd == "carveout":
        _p(p.carve_out(a.tenant))
    elif a.cmd == "audit":
        _p(p.store.verify_audit() if a.verify else p.store.audit_log(a.tenant, a.limit))
    elif a.cmd == "serve":
        from .api import serve
        serve(p, a.host, a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
