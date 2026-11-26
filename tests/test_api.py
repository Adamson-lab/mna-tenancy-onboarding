import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from mnatenancy.api import make_handler

from .conftest import deal


@pytest.fixture
def server(platform):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(platform))
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def call(url, method="GET", body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers["Content-Type"].startswith("application/json") else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_full_flow_over_http(server):
    code, r = call(f"{server}/api/deals", "POST", deal("initech-cloud"))
    assert code == 201 and r["tenant_id"] == "northwind-initech-cloud"
    tid = r["tenant_id"]

    code, d = call(f"{server}/api/authorize", "POST",
                   {"principal": "northwind:cro", "action": "read_customer_data", "tenant": tid})
    assert code == 403 and d["rule"] == "R1"

    for _ in range(3):
        code, a = call(f"{server}/api/tenants/{tid}/advance", "POST", {"actor": "test"})
        assert code == 200, a
    code, d = call(f"{server}/api/authorize", "POST",
                   {"principal": "northwind:cro", "action": "read_customer_data", "tenant": tid})
    assert code == 200 and d["allow"]

    code, pf = call(f"{server}/api/portfolio")
    assert code == 200 and pf["audit"]["valid"] and pf["tenants"][0]["tier"] == "pool"

    code, html = call(f"{server}/")
    assert code == 200 and b"M&amp;A Tenancy Control Plane" in html
    code, mmd = call(f"{server}/api/hierarchy.mmd")
    assert b"flowchart TD" in mmd


def test_gate_blocked_returns_409(server):
    _, r = call(f"{server}/api/deals", "POST", deal("globex-bank"))
    code, a = call(f"{server}/api/tenants/{r['tenant_id']}/advance", "POST", {})
    assert code == 409 and "deal has not legally closed" in a["failures"]


def test_unknown_tenant_404(server):
    code, _ = call(f"{server}/api/tenants/nope")
    assert code == 404
