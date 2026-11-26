# ADR-002: Federate the acquired IdP on Day 1; don't merge it

**Status:** Accepted

**Context.** Merging directories on Day 1 brings over stale accounts, MFA gaps and toxic role combinations that only become visible once groups are mapped to the parent's roles.

**Decision.** Acquired groups are mapped to parent roles **scoped to the acquired tenant**. SoD conflicts are found at mapping time and the approval side is quarantined. Unmapped groups block the Day-100 → Day-365 gate. Parent roles inherit into the tenant only as the tier and phase allow (policy rule R6).

**Consequences.** + Fraud paths never go live. + Users keep working on Day 1. − A temporary dual-identity period (federation) has to be run and monitored.
