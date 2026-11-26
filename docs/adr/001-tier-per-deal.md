# ADR-001: Tenancy tier is decided per deal and changes over time

**Status:** Accepted

**Context.** Enterprises usually choose one integration architecture ("everything goes into the corporate tenant", or "everything stays standalone"). Acquisitions vary too much for that to work: a SaaS tuck-in, a regulated bank and a defence contractor need very different treatment.

**Decision.** Each deal gets a Day-1 tier and a target tier from an explainable engine (`tiering.py`). Hard constraints (sovereign regimes, unserved residency, pending approval) override economics. Phase gates move the tenant along its convergence path, and moving it re-renders the infrastructure.

**Consequences.** + Fast, safe integration matched to risk. + Synergy is visible per tier. − Three infrastructure patterns to maintain (mitigated by the Terraform modules). − Requires discipline in filling in the deal manifest.
