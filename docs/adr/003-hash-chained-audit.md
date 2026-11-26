# ADR-003: Hash-chained, append-only audit log

**Status:** Accepted

**Context.** Regulators, external auditors and antitrust counsel need evidence of who accessed target data, when, and under which rule, and assurance that the evidence hasn't been altered.

**Decision.** Every authorisation decision and lifecycle event is appended with `sha256(prev_hash | ts | actor | action | tenant | severity | detail)`. `verify_audit()` recomputes the chain. In production the table is append-only (`REVOKE UPDATE, DELETE`) and the chain head is periodically anchored to WORM storage.

**Consequences.** + Tampering is detectable down to the exact row (shown in demo step 13). − It detects tampering but doesn't prevent it; anchoring provides prevention.
