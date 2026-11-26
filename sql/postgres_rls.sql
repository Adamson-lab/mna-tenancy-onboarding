-- Production data plane: PostgreSQL Row-Level Security for POOLED tenants,
-- schema-per-tenant for BRIDGED tenants. SILO tenants get their own cluster.
--
-- The app sets the tenant scope per transaction from the policy engine's decision:
--   SET LOCAL app.tenant_ids = 'northwind,northwind-initech-cloud';

CREATE ROLE app_rw NOLOGIN;

CREATE TABLE IF NOT EXISTS records (
  id             bigserial PRIMARY KEY,
  tenant_id      text        NOT NULL,
  kind           text        NOT NULL,
  classification text        NOT NULL DEFAULT 'internal',
  payload        jsonb       NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_records_tenant ON records (tenant_id);

ALTER TABLE records ENABLE ROW LEVEL SECURITY;
ALTER TABLE records FORCE ROW LEVEL SECURITY;   -- even the table owner is filtered

CREATE OR REPLACE FUNCTION app_tenant_scope() RETURNS text[]
LANGUAGE sql STABLE AS $$
  SELECT string_to_array(nullif(current_setting('app.tenant_ids', true), ''), ',')
$$;

-- Reads: only rows whose tenant is in the scope. Empty scope => zero rows (fail closed).
CREATE POLICY tenant_read ON records FOR SELECT TO app_rw
  USING (tenant_id = ANY (coalesce(app_tenant_scope(), ARRAY[]::text[])));

-- Writes: cannot insert/update into a tenant outside scope.
CREATE POLICY tenant_write ON records FOR INSERT TO app_rw
  WITH CHECK (tenant_id = ANY (coalesce(app_tenant_scope(), ARRAY[]::text[])));
CREATE POLICY tenant_update ON records FOR UPDATE TO app_rw
  USING (tenant_id = ANY (coalesce(app_tenant_scope(), ARRAY[]::text[])))
  WITH CHECK (tenant_id = ANY (coalesce(app_tenant_scope(), ARRAY[]::text[])));

GRANT SELECT, INSERT, UPDATE ON records TO app_rw;
GRANT USAGE ON SEQUENCE records_id_seq TO app_rw;

-- BRIDGE tenant template: own schema, own owner role, KMS-wrapped credentials.
-- (Rendered per tenant by the bridge module; shown for northwind-globex-bank.)
CREATE SCHEMA IF NOT EXISTS t_northwind_globex_bank;
CREATE ROLE t_northwind_globex_bank_owner NOLOGIN;
ALTER SCHEMA t_northwind_globex_bank OWNER TO t_northwind_globex_bank_owner;
REVOKE ALL ON SCHEMA t_northwind_globex_bank FROM PUBLIC;

-- Append-only audit table: no UPDATE/DELETE for anyone but a break-glass role.
CREATE TABLE IF NOT EXISTS audit (
  seq bigserial PRIMARY KEY, ts timestamptz NOT NULL, actor text NOT NULL, action text NOT NULL,
  tenant_id text, severity text NOT NULL, detail jsonb NOT NULL, prev_hash char(64) NOT NULL, hash char(64) NOT NULL
);
REVOKE UPDATE, DELETE, TRUNCATE ON audit FROM PUBLIC, app_rw;
GRANT INSERT, SELECT ON audit TO app_rw;
