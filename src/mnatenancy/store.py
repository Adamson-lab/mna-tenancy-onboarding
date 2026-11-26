"""Persistence: SQLite for the reference implementation (zero dependencies).

Production uses PostgreSQL with native Row-Level Security - see sql/postgres_rls.sql.
Here, tenant isolation for POOLED data is enforced by `TenantScopedRepo`: there is no
code path that reads `records` without a tenant predicate, and tests prove it.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .models import Phase, Tenant, Tier

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT, tier TEXT NOT NULL,
  target_tier TEXT NOT NULL, phase TEXT NOT NULL, regions TEXT NOT NULL, regimes TEXT NOT NULL,
  deal_id TEXT, attributes TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS principals (
  principal_id TEXT PRIMARY KEY, home_tenant TEXT NOT NULL, attributes TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS grants (
  principal_id TEXT NOT NULL, tenant_id TEXT NOT NULL, role TEXT NOT NULL, source TEXT,
  PRIMARY KEY (principal_id, tenant_id, role)
);
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, kind TEXT NOT NULL,
  classification TEXT NOT NULL DEFAULT 'internal', payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_records_tenant ON records(tenant_id);
CREATE TABLE IF NOT EXISTS tsa (
  tenant_id TEXT NOT NULL, name TEXT NOT NULL, provider TEXT, monthly_cost REAL,
  end_date TEXT, exit_plan TEXT, PRIMARY KEY (tenant_id, name)
);
CREATE TABLE IF NOT EXISTS usage (
  tenant_id TEXT NOT NULL, resource TEXT NOT NULL, units REAL NOT NULL,
  PRIMARY KEY (tenant_id, resource)
);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, tenant_id TEXT, severity TEXT NOT NULL, detail TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
"""

GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self.db
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    # ------------------------------------------------------------------ tenants
    def put_tenant(self, t: Tenant) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO tenants VALUES (?,?,?,?,?,?,?,?,?,?)",
                (t.tenant_id, t.name, t.parent_id, t.tier.value, t.target_tier.value, t.phase.value,
                 json.dumps(t.regions), json.dumps(t.regimes), t.deal_id, json.dumps(t.attributes)),
            )

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        r = self.db.execute("SELECT * FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
        return self._row_to_tenant(r) if r else None

    def list_tenants(self) -> list[Tenant]:
        return [self._row_to_tenant(r) for r in self.db.execute("SELECT * FROM tenants ORDER BY tenant_id")]

    @staticmethod
    def _row_to_tenant(r) -> Tenant:
        return Tenant(r["tenant_id"], r["name"], r["parent_id"], Tier(r["tier"]), Tier(r["target_tier"]),
                      Phase(r["phase"]), json.loads(r["regions"]), json.loads(r["regimes"]), r["deal_id"],
                      json.loads(r["attributes"]))

    # --------------------------------------------------------------- principals
    def put_principal(self, pid: str, home: str, attrs: dict | None = None) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO principals VALUES (?,?,?)", (pid, home, json.dumps(attrs or {})))

    def get_principal(self, pid: str) -> dict | None:
        r = self.db.execute("SELECT * FROM principals WHERE principal_id=?", (pid,)).fetchone()
        if not r:
            return None
        return {"principal_id": r["principal_id"], "home_tenant": r["home_tenant"],
                "attributes": json.loads(r["attributes"]), "grants": self.grants_for(pid)}

    def grant(self, pid: str, tenant_id: str, role: str, source: str = "manual") -> None:
        with self.tx() as db:
            db.execute("INSERT OR IGNORE INTO grants VALUES (?,?,?,?)", (pid, tenant_id, role, source))

    def revoke_tenant_grants(self, tenant_id: str) -> int:
        with self.tx() as db:
            return db.execute("DELETE FROM grants WHERE tenant_id=?", (tenant_id,)).rowcount

    def grants_for(self, pid: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for r in self.db.execute("SELECT tenant_id, role FROM grants WHERE principal_id=? ORDER BY role", (pid,)):
            out.setdefault(r["tenant_id"], []).append(r["role"])
        return out

    # ---------------------------------------------------------------- tsa/usage
    def put_tsa(self, tenant_id: str, s) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO tsa VALUES (?,?,?,?,?,?)",
                       (tenant_id, s.name, s.provider, s.monthly_cost, s.end_date, s.exit_plan))

    def list_tsa(self, tenant_id: str | None = None) -> list[dict]:
        q, a = "SELECT * FROM tsa", ()
        if tenant_id:
            q, a = q + " WHERE tenant_id=?", (tenant_id,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY end_date", a)]

    def put_usage(self, tenant_id: str, usage: dict[str, float]) -> None:
        with self.tx() as db:
            for res, units in usage.items():
                db.execute("INSERT OR REPLACE INTO usage VALUES (?,?,?)", (tenant_id, res, units))

    def usage(self, tenant_id: str) -> dict[str, float]:
        return {r["resource"]: r["units"] for r in
                self.db.execute("SELECT resource, units FROM usage WHERE tenant_id=?", (tenant_id,))}

    # -------------------------------------------------------------------- audit
    def audit(self, actor: str, action: str, tenant_id: str | None, detail: dict,
              severity: str = "info") -> str:
        with self.tx() as db:
            last = db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = last["hash"] if last else GENESIS
            ts = _now()
            body = json.dumps(detail, sort_keys=True, default=str)
            h = _chain_hash(prev, ts, actor, action, tenant_id, severity, body)
            db.execute("INSERT INTO audit (ts,actor,action,tenant_id,severity,detail,prev_hash,hash) "
                       "VALUES (?,?,?,?,?,?,?,?)", (ts, actor, action, tenant_id, severity, body, prev, h))
            return h

    def audit_log(self, tenant_id: str | None = None, limit: int = 200) -> list[dict]:
        q, a = "SELECT * FROM audit", ()
        if tenant_id:
            q, a = q + " WHERE tenant_id=?", (tenant_id,)
        rows = self.db.execute(q + " ORDER BY seq DESC LIMIT ?", (*a, limit)).fetchall()
        return [dict(r) | {"detail": json.loads(r["detail"])} for r in rows]

    def verify_audit(self) -> dict:
        prev, n = GENESIS, 0
        for r in self.db.execute("SELECT * FROM audit ORDER BY seq"):
            n += 1
            expect = _chain_hash(prev, r["ts"], r["actor"], r["action"], r["tenant_id"], r["severity"], r["detail"])
            if r["prev_hash"] != prev or r["hash"] != expect:
                return {"valid": False, "entries": n, "broken_at_seq": r["seq"]}
            prev = r["hash"]
        return {"valid": True, "entries": n, "head": prev}


def _chain_hash(prev, ts, actor, action, tenant_id, severity, body) -> str:
    material = "|".join([prev, ts, actor, action, tenant_id or "", severity, body])
    return hashlib.sha256(material.encode()).hexdigest()


class CrossTenantViolation(PermissionError):
    pass


class TenantScopedRepo:
    """The ONLY way application code touches pooled business records.

    Constructed with the set of tenant ids the caller is entitled to (resolved by the
    policy engine). Every query is forced through a tenant predicate; writes to a tenant
    outside scope raise `CrossTenantViolation`.
    """

    def __init__(self, store: Store, allowed_tenants: set[str]):
        if not allowed_tenants:
            raise CrossTenantViolation("empty tenant scope")
        self.s = store
        self.allowed = frozenset(allowed_tenants)

    def _check(self, tenant_id: str) -> None:
        if tenant_id not in self.allowed:
            raise CrossTenantViolation(f"tenant {tenant_id} not in scope {sorted(self.allowed)}")

    def insert(self, tenant_id: str, kind: str, payload: dict, classification: str = "internal") -> int:
        self._check(tenant_id)
        with self.s.tx() as db:
            return db.execute("INSERT INTO records (tenant_id,kind,classification,payload) VALUES (?,?,?,?)",
                              (tenant_id, kind, classification, json.dumps(payload))).lastrowid

    def query(self, kind: str | None = None) -> list[dict]:
        marks = ",".join("?" * len(self.allowed))
        q = f"SELECT * FROM records WHERE tenant_id IN ({marks})"
        args: list = list(self.allowed)
        if kind:
            q += " AND kind=?"
            args.append(kind)
        return [dict(r) | {"payload": json.loads(r["payload"])} for r in self.s.db.execute(q + " ORDER BY id", args)]

    def count(self, tenant_id: str) -> int:
        self._check(tenant_id)
        return self.s.db.execute("SELECT COUNT(*) FROM records WHERE tenant_id=?", (tenant_id,)).fetchone()[0]

    def purge(self, tenant_id: str) -> int:
        self._check(tenant_id)
        with self.s.tx() as db:
            return db.execute("DELETE FROM records WHERE tenant_id=?", (tenant_id,)).rowcount
