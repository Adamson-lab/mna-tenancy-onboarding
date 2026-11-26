-- Proves RLS fails closed and blocks cross-tenant reads/writes. Run after postgres_rls.sql.
\set ON_ERROR_STOP 1
INSERT INTO records (tenant_id, kind, payload) VALUES
  ('northwind-globex-bank', 'customer', '{"n":1}'),
  ('northwind-initech-cloud', 'customer', '{"n":2}');
CREATE ROLE rls_tester LOGIN IN ROLE app_rw;
SET ROLE rls_tester;

BEGIN;
DO $$ BEGIN
  IF (SELECT count(*) FROM records) <> 0 THEN RAISE EXCEPTION 'empty scope must see 0 rows'; END IF;
END $$;
SET LOCAL app.tenant_ids = 'northwind-initech-cloud';
DO $$ BEGIN
  IF (SELECT count(*) FROM records WHERE tenant_id = 'northwind-globex-bank') <> 0 THEN
    RAISE EXCEPTION 'cross-tenant read leaked'; END IF;
  IF (SELECT count(*) FROM records) <> 1 THEN RAISE EXCEPTION 'expected 1 scoped row'; END IF;
  BEGIN
    INSERT INTO records (tenant_id, kind, payload) VALUES ('northwind-globex-bank', 'x', '{}');
    RAISE EXCEPTION 'cross-tenant write was allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL;  -- expected: RLS WITH CHECK violation
  END;
END $$;
COMMIT;
\echo 'RLS tests passed'
