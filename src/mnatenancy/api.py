"""Zero-dependency JSON API + executive dashboard (stdlib http.server).

Run:  python -m mnatenancy serve --port 8080   ->  http://localhost:8080
"""
from __future__ import annotations

import json
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from .service import Platform

ROUTES: list[tuple[str, str, str]] = [
    ("GET", r"^/healthz$", "health"),
    ("GET", r"^/$", "dashboard"),
    ("GET", r"^/api/portfolio$", "portfolio"),
    ("GET", r"^/api/tenants$", "tenants"),
    ("GET", r"^/api/tenants/(?P<tid>[\w-]+)$", "tenant"),
    ("POST", r"^/api/tenants/(?P<tid>[\w-]+)/advance$", "advance"),
    ("POST", r"^/api/tenants/(?P<tid>[\w-]+)/remediate$", "remediate"),
    ("POST", r"^/api/tenants/(?P<tid>[\w-]+)/sod/resolve$", "resolve_sod"),
    ("POST", r"^/api/tenants/(?P<tid>[\w-]+)/tsa/exit-plan$", "exit_plan"),
    ("POST", r"^/api/tenants/(?P<tid>[\w-]+)/carveout$", "carveout"),
    ("POST", r"^/api/deals$", "onboard"),
    ("POST", r"^/api/authorize$", "authorize"),
    ("GET", r"^/api/records$", "records"),
    ("GET", r"^/api/audit$", "audit"),
    ("GET", r"^/api/audit/verify$", "audit_verify"),
    ("GET", r"^/api/hierarchy.mmd$", "hierarchy"),
]


def hierarchy_mermaid(p: Platform) -> str:
    lines = ["flowchart TD"]
    style = {"silo": ":::silo", "bridge": ":::bridge", "pool": ":::pool"}
    for t in p.store.list_tenants():
        label = f'{t.name}<br/>{t.tier.value.upper()} → {t.target_tier.value.upper()}<br/><i>{t.phase.value}</i>'
        node_id = t.tenant_id.replace("-", "_")
        lines.append(f'  {node_id}["{label}"]{style[t.tier.value] if t.parent_id else ":::parent"}')
        if t.parent_id:
            lines.append(f'  {t.parent_id.replace("-", "_")} --> {node_id}')
    lines += ["  classDef parent fill:#1f3a5f,color:#fff,stroke:#1f3a5f",
              "  classDef silo fill:#7a1f2b,color:#fff,stroke:#7a1f2b",
              "  classDef bridge fill:#8a5a00,color:#fff,stroke:#8a5a00",
              "  classDef pool fill:#1d6b46,color:#fff,stroke:#1d6b46"]
    return "\n".join(lines)


def make_handler(p: Platform):
    class Handler(BaseHTTPRequestHandler):
        server_version = "mnat/1.0"

        def log_message(self, fmt, *args):  # quieter logs
            pass

        def _send(self, code: int, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else (
                body.encode() if isinstance(body, str) else json.dumps(body, indent=2, default=str).encode())
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _route(self, method: str):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            for m, pattern, name in ROUTES:
                if m != method:
                    continue
                mt = re.match(pattern, u.path)
                if mt:
                    try:
                        code, body, *ct = getattr(self, "h_" + name)(q=q, **mt.groupdict())
                        return self._send(code, body, *(ct or ["application/json"]))
                    except KeyError as e:
                        return self._send(404, {"error": f"not found: {e}"})
                    except (ValueError, PermissionError) as e:
                        return self._send(400, {"error": str(e)})
                    except Exception as e:  # pragma: no cover
                        traceback.print_exc()
                        return self._send(500, {"error": repr(e)})
            self._send(404, {"error": "no route"})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        # ---- handlers
        def h_health(self, q):
            return 200, {"status": "ok", "audit": p.store.verify_audit()}

        def h_dashboard(self, q):
            html = resources.files("mnatenancy").joinpath("dashboard.html").read_text()
            return 200, html, "text/html; charset=utf-8"

        def h_portfolio(self, q):
            return 200, p.portfolio()

        def h_tenants(self, q):
            return 200, [p.tenant_view(t.tenant_id)["tenant"] for t in p.store.list_tenants()]

        def h_tenant(self, q, tid):
            return 200, p.tenant_view(tid)

        def h_advance(self, q, tid):
            b = self._body()
            r = p.advance(tid, b.get("actor", "api"), bool(b.get("force")))
            return (200 if r["advanced"] else 409), r

        def h_remediate(self, q, tid):
            b = self._body()
            return 200, p.remediate(tid, b["field"], b["value"], b.get("actor", "api"))

        def h_resolve_sod(self, q, tid):
            b = self._body()
            return 200, p.resolve_sod(tid, b["principal"], b["drop_role"], b.get("actor", "api"))

        def h_exit_plan(self, q, tid):
            b = self._body()
            return 200, p.tsa_exit_plan(tid, b["service"], b["plan"], b.get("actor", "api"))

        def h_carveout(self, q, tid):
            return 200, p.carve_out(tid, self._body().get("actor", "api"))

        def h_onboard(self, q):
            return 201, p.onboard(self._body(), q.get("actor", "api"))

        def h_authorize(self, q):
            b = self._body()
            d = p.authorize(b["principal"], b["action"], b["tenant"], b.get("ctx"))
            return (200 if d["allow"] else 403), d

        def h_records(self, q):
            ctx = {"region": q["region"]} if "region" in q else None
            return 200, p.records(q["principal"], q.get("action", "read_customer_data"), ctx)

        def h_audit(self, q):
            return 200, p.store.audit_log(q.get("tenant"), int(q.get("limit", 100)))

        def h_audit_verify(self, q):
            return 200, p.store.verify_audit()

        def h_hierarchy(self, q):
            return 200, hierarchy_mermaid(p), "text/plain; charset=utf-8"

    return Handler


def serve(p: Platform, host: str = "0.0.0.0", port: int = 8080) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(p))
    print(f"mnat control plane on http://{host}:{port}  (db={p.db_path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
