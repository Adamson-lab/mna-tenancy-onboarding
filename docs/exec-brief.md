# Executive brief: tenancy model for M&A onboarding

**Audience:** CEO, CFO, CIO, CISO, General Counsel, Board Risk Committee
**Decision requested:** Adopt *tier-per-deal with gated convergence* as the integration standard for all acquisitions.

## The problem
Most of the value of an acquisition sits in the synergy case, and most synergy depends on technology integration. Integration fails in two opposite ways:

1. **Too slow.** The acquired company runs on transition service agreements (TSAs) for years. The seller keeps billing, synergies slip, and the board loses patience.
2. **Too fast.** Directories get merged, networks peered and data pooled in the first month. That brings over the target's fraud paths, MFA gaps and unpatched systems, can move regulated data across borders, and, if anything happens before close, risks gun-jumping penalties.

A third failure mode shows up years later: a regulator orders a **divestiture** and the business can't be separated.

## The model
Every acquisition gets **three answers, decided per deal and recorded with the reasons**:

| Answer | Options | Decided by |
|---|---|---|
| Day-1 isolation | SILO / BRIDGE | Risk score + hard legal constraints |
| Target end state | SILO / BRIDGE / POOL | Deal intent (absorb / preserve / divest-likely) + constraints |
| Gate criteria | Pre-close → Day 1 → Day 100 → Day 365 | Close, SoD, MFA, criticals, TSA exit plans |

The invariant that protects the firm: **a company is never less isolated on Day 1 than it will be at the end.**

## What the board gets
- **One portfolio view.** Every acquired company, its tier, phase, blockers, platform cost, TSA burn and synergy at target.
- **Provable controls.** Every access decision is logged in a tamper-evident chain that regulators and auditors can verify.
- **Antitrust safety.** Before close, only the clean team can see target data, and only aggregated data. The rule is enforced in code, not left to policy documents.
- **Sovereignty built in.** Federal (FedRAMP/ITAR/CMMC) and data-localised acquisitions (NDPR, DORA, GDPR) are siloed automatically and region-locked.
- **Optionality.** Every tenant can be carved out with an evidence manifest: records exported with a hash, zero residual rows, all grants revoked.

## Sample portfolio (from the reference run)
| Company | Day-1 → Target | Why | Annualised synergy* |
|---|---|---|---|
| Globex Bank (EU retail bank) | SILO → BRIDGE | Risk 15: PCI, DORA, 71% MFA, 2 criticals, legacy AD | $4.5M (mostly TSA exit) |
| Initech Cloud (SaaS tuck-in) | BRIDGE → POOL | Risk 0, absorb | $0.2M |
| Umbrella Federal Systems | SILO → SILO | FedRAMP-High / ITAR, GovCloud residency | $0, carved out on regulator order |
| Sahel Pay (Nigerian fintech) | SILO → SILO | NDPR sovereign, af-south-1, CBN approval pending | Clean room until approval |

\*Illustrative rate card.

## Asks
1. Mandate a deal manifest at signing for every acquisition over $50M.
2. Make Day-100 gate status a standing item in the board's integration report.
3. Fund a regional cell in each residency zone where acquisitions are expected, so silos can converge.
