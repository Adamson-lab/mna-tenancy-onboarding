# M&A Tenancy Control Plane

**Isolate on Day 1. Converge by Day 365. Carve out in a weekend.**

A working control plane for onboarding acquired companies into a parent's platform. It is built for the problem CEOs, CFOs, CIOs, CISOs and General Counsel at Fortune 100 companies, banks, federal agencies and parastatals actually face after the deal is signed. In one sentence:

> *"How do we bring this company in fast enough to bank the synergies, without breaching antitrust rules before close, leaking regulated data across borders, inheriting their fraud paths, or making a forced divestiture impossible?"*

It runs today with **zero runtime dependencies** (Python 3.10+ stdlib only). It has 28 tests, a 13-step scripted demo, a live dashboard and JSON API, Terraform modules for each tenancy tier, Postgres Row-Level Security with its own test, and the diagrams below.

![Executive dashboard](docs/dashboard.png)

```bash
git clone <this repo> && cd mna-tenancy-onboarding
make demo        # 13-step walkthrough: 4 acquisitions, every control exercised
make serve       # same, then the live dashboard at http://localhost:8080
make test        # 28 tests
docker compose up --build   # control plane + Postgres with RLS
```

---

## The problem, in board language

| Executive | Question this repo answers | Where |
|---|---|---|
| **CEO / Board** | Which acquisitions are on track for Day 100, and what is blocking the rest? | Phase gates, dashboard |
| **CFO** | What synergy do we unlock by converging each tenant, and what is the TSA burn? | `finance.py`, dashboard KPIs |
| **General Counsel** | Can anyone outside the clean team see target data before close (gun-jumping)? | Policy rule **R1** |
| **CISO** | Are their admins, MFA gaps and toxic role combinations coming in with them? | Identity federation, Day-1 gate |
| **CRO / Compliance** | Does EU, Nigerian or US-federal data stay where the law says it must? | Rules **R2/R3**, SCP region lock |
| **CIO** | Silo, bridge or pool for each deal, and what does the landing zone look like? | Tiering engine, Terraform |
| **Regulator / Auditor** | Show me every access decision and prove nobody edited the log. | Hash-chained audit |
| **Board (exit)** | If we are ordered to divest, can we hand it back cleanly, with evidence? | Carve-out engine |

---

## Architecture

```mermaid
flowchart TB
  DM[/"Deal manifest<br/>regimes · residency · IdP · findings · TSA · intent"/]
  IdP["Acquired IdP<br/>AD / Entra / Okta"]
  APP["Apps & users"]
  DASH["Exec dashboard + JSON API"]

  subgraph CP["mnat control plane"]
    direction TB
    TE["Tiering engine<br/>risk score + hard constraints"]
    IDF["Identity federation<br/>group→role · SoD quarantine"]
    REG[("Tenant registry<br/>hierarchy · tier · phase")]
    PH["Phase gates<br/>Pre-close → D1 → D100 → D365"]
    PDP["Policy decision point<br/>ABAC rules R0–R6"]
    FIN["Finance<br/>chargeback · TSA · synergy"]
    CO["Carve-out engine"]
    AUD[("Hash-chained audit log")]
  end

  subgraph DP["Infra & data planes"]
    direction LR
    TF["Terraform modules<br/>silo · bridge · pool"]
    SCOPE["TenantScopedRepo"]
    RLS[("Postgres RLS<br/>schema-per-bridge")]
  end

  DM --> TE --> REG
  IdP --> IDF --> REG
  REG --> PH
  REG --> FIN
  PH -->|"tier migration → tfvars"| TF
  APP -->|request| PDP
  PDP -->|reads| REG
  PDP -->|"tenant scope"| SCOPE --> RLS
  CO --> SCOPE
  PH & PDP & CO -.->|every decision| AUD
  DASH --> CP
```
<sub>Source: [`docs/diagrams/01-architecture.mmd`](docs/diagrams/01-architecture.mmd) · [SVG](docs/diagrams/01-architecture.svg)</sub>

## Three tenancy tiers, one convergence path

Pick the wrong tenancy model and you either stall the integration, which costs you synergies, or merge too fast and breach a regulator or the antitrust rules. This repo makes the tenancy model **a per-deal decision that changes over time**, not one architecture applied to everyone.

```mermaid
flowchart TB
  subgraph SILO["SILO — dedicated everything"]
    direction TB
    S1["Own AWS account (M&A OU)<br/>SCP region lock"]
    S2["Own VPC · NO peering to parent"]
    S3["Own DB cluster · own KMS key"]
    S4["Own log archive (object-lock)"]
  end
  subgraph BRIDGE["BRIDGE — shared control plane, own data boundary"]
    direction TB
    B1["Shared platform account"]
    B2["Transit GW route table<br/>→ inspection VPC"]
    B3["Own DB schema + own KMS key<br/>(crypto-shred on exit)"]
    B4["ABAC: PrincipalTag tenant_id"]
  end
  subgraph POOL["POOL — fully absorbed"]
    direction TB
    P1["Shared everything"]
    P2["Postgres RLS on tenant_id"]
    P3["Parent roles inherit (≥ Day 365)"]
  end
  SILO -- "Day 100: risk remediated" --> BRIDGE
  BRIDGE -- "Day 365: intent = absorb, risk ≤ 4" --> POOL
  POOL -. "carve-out = export + purge" .-> EXIT(["Divested entity"])
  SILO -. "carve-out = lift account" .-> EXIT
  classDef s fill:#7a1f2b,color:#fff,stroke:#7a1f2b
  classDef b fill:#8a5a00,color:#fff,stroke:#8a5a00
  classDef p fill:#1d6b46,color:#fff,stroke:#1d6b46
  class S1,S2,S3,S4 s
  class B1,B2,B3,B4 b
  class P1,P2,P3 p
```
<sub>Source: [`docs/diagrams/02-tenancy-tiers.mmd`](docs/diagrams/02-tenancy-tiers.mmd) · [SVG](docs/diagrams/02-tenancy-tiers.svg)</sub>

| | SILO | BRIDGE | POOL |
|---|---|---|---|
| Isolation | Dedicated account, VPC, DB, KMS | Dedicated schema + KMS on a shared platform | Row-level (`tenant_id`) |
| Network to parent | **None** | Transit GW, forced through inspection | Shared |
| Parent roles inherit? | Never | Consolidation only (finance/audit read) | Fully, from Day 365 |
| Fixed platform cost/mo* | $42,000 | $11,000 | $1,500 |
| Carve-out | Lift the account | Crypto-shred key + drop schema | Export + purge rows |
| Typical deal | FedRAMP / ITAR / sovereign, divest-likely | Regulated bank, standalone brand | SaaS tuck-in |

\*Illustrative rate card. Override with `rates/ratecard.json`.

## How the tier is decided

Every decision is **explainable**. The engine returns each risk point and each hard constraint as a sentence an auditor can read.

```mermaid
flowchart TD
  A(["Deal manifest"]) --> B{"Sovereign regime?<br/>FedRAMP-High · ITAR · CJIS<br/>CMMC-L3 · NDPR-Sovereign"}
  B -- yes --> SILO1["Target = SILO forever"]
  B -- no --> C{"Residency region<br/>served by parent?"}
  C -- no --> SILO2["Target = regional SILO<br/>until a cell exists"]
  C -- yes --> D{"Intent"}
  D -- divest_likely --> SILO3["Target = SILO<br/>(carve-out-ready)"]
  D -- preserve --> BR["Target = BRIDGE"]
  D -- absorb --> E{"Risk score ≤ 4?<br/>regimes + criticals +<br/>MFA gap + legacy AD"}
  E -- yes --> PO["Target = POOL"]
  E -- no --> BR2["Target = BRIDGE"]
  SILO1 & SILO2 & SILO3 & BR & PO & BR2 --> F{"Hard constraint<br/>or risk ≥ 5?"}
  F -- yes --> D1S["Day-1 = SILO"]
  F -- "risk 2–4" --> D1B["Day-1 = BRIDGE"]
  F -- "risk < 2" --> D1T["Day-1 = BRIDGE (or target if more isolated)"]
  D1S & D1B & D1T --> G["Invariant: Day-1 isolation ≥ target isolation"]
```
<sub>Source: [`docs/diagrams/03-decision-tree.mmd`](docs/diagrams/03-decision-tree.mmd) · [SVG](docs/diagrams/03-decision-tree.svg)</sub>

Output for the four sample deals (from `make demo`):

```
  target                     risk  day-1   target   hard constraints
  globex-bank                  15  silo    bridge   -
  initech-cloud                 0  bridge  pool     -
  umbrella-federal-systems      1  silo    silo     sovereign regime(s) ['CMMC-L3','FedRAMP-High','ITAR'] -> dedicated SILO, never pooled; residency ['us-gov-west-1'] not served ...
  sahel-pay                     8  silo    silo     sovereign regime(s) ['NDPR-Sovereign'] ...; residency ['af-south-1'] not served ...; regulatory approval pending ...
```

## Integration lifecycle with hard gates

A tenant **cannot** advance while a gate fails, unless someone forces it, which is recorded as a CRITICAL audit event listing the waived failures. When a tenant advances, it moves to the next tier on its convergence path and its Terraform tfvars are re-rendered, so `terraform plan` shows the infrastructure move.

```mermaid
stateDiagram-v2
  direction LR
  [*] --> PRE_CLOSE: deal signed
  PRE_CLOSE --> DAY_1: gate ✓ legally closed<br/>✓ regulator approved<br/>✓ landing zone provisioned
  DAY_1 --> DAY_100: gate ✓ 0 live SoD conflicts<br/>✓ MFA ≥ 90%<br/>✓ 0 critical findings<br/>✓ audit chain valid
  DAY_100 --> DAY_365: gate ✓ every TSA has exit plan<br/>✓ no unmapped IdP groups
  DAY_365 --> INTEGRATED: gate ✓ all TSAs exited
  PRE_CLOSE --> CARVED_OUT: deal blocked / remedy
  DAY_1 --> CARVED_OUT
  DAY_100 --> CARVED_OUT
  DAY_365 --> CARVED_OUT
  INTEGRATED --> CARVED_OUT: divestiture
  note right of PRE_CLOSE
    clean-team only, aggregated data only
    (HSR Act / EU Merger Reg gun-jumping)
    clean team auto-dissolved at close
  end note
  note right of DAY_100
    tier migrates per convergence path
    tfvars re-rendered → terraform plan
  end note
```
<sub>Source: [`docs/diagrams/04-lifecycle.mmd`](docs/diagrams/04-lifecycle.mmd) · [SVG](docs/diagrams/04-lifecycle.svg)</sub>

```mermaid
gantt
  title Integration timeline (Globex Bank, DEAL-2026-014)
  dateFormat YYYY-MM-DD
  axisFormat %b %y
  section Pre-close
  Clean team (aggregated data only)   :a1, 2026-11-01, 30d
  Landing zone rendered (SILO)        :a2, 2026-11-10, 10d
  section Day 1
  Legal close + clean team dissolved  :milestone, m1, 2026-12-01, 0d
  Identity federation + SoD quarantine:b1, 2026-12-01, 14d
  MFA rollout 71 to 94 pct               :b2, 2026-12-01, 60d
  Close 2 critical findings           :b3, 2026-12-05, 45d
  section Day 100
  Migrate SILO to BRIDGE               :milestone, m2, 2027-03-10, 0d
  TSA exit - payroll                   :c1, 2027-01-01, 31d
  TSA exit - SWIFT gateway             :crit, c2, 2027-01-15, 31d
  section Day 365
  TSA exit - core banking hosting      :d1, 2027-04-01, 183d
  Target tier reached (BRIDGE)        :milestone, m3, 2027-12-01, 0d
```
<sub>Source: [`docs/diagrams/09-integration-timeline.mmd`](docs/diagrams/09-integration-timeline.mmd) · [SVG](docs/diagrams/09-integration-timeline.svg)</sub>

## Access control: every request, every rule, every time

Rules are evaluated deny-first. Every decision, allow or deny, is written to the audit chain along with the rule that decided it.

| Rule | What it enforces | Why the executive cares |
|---|---|---|
| **R0** | Tenant exists and is not carved out | Divested means divested |
| **R1** | Pre-close: clean team only, aggregated data only | HSR Act / EU Merger Regulation gun-jumping fines |
| **R2** | Sovereign tenants require `us_person` (or local-national) | ITAR / FedRAMP / NDPR |
| **R3** | Customer or PII access must come from a permitted region | GDPR, DORA, data-localisation laws |
| **R4** | Break-glass needs parent `security_admin` + justification; logged CRITICAL | Incident response without standing access |
| **R5** | Direct grant on the target tenant | Least privilege |
| **R6** | Parent roles inherit only as the tier and phase allow | "Bridge" really is a bridge |

```mermaid
sequenceDiagram
  autonumber
  actor U as northwind:cro
  participant API as API / app
  participant PDP as Policy engine
  participant REG as Tenant registry
  participant REPO as TenantScopedRepo
  participant DB as Postgres (RLS)
  participant AUD as Audit chain
  U->>API: GET /api/records?action=read_customer_data
  API->>PDP: allowed_tenants(cro, read_customer_data)
  loop each tenant
    PDP->>REG: tier, phase, regimes, regions
    Note over PDP: R0 exists · R1 pre-close guard · R2 sovereign<br/>R3 residency · R4 break-glass · R5 direct · R6 inherit
  end
  PDP-->>API: scope = {northwind, northwind-initech-cloud}
  API->>REPO: TenantScopedRepo(scope).query()
  REPO->>DB: SET LOCAL app.tenant_ids=...<br/>SELECT ... WHERE tenant_id = ANY(scope)
  DB-->>REPO: rows (Globex excluded: BRIDGE)
  API->>AUD: records:read {scope, rows} → sha256(prev ‖ entry)
  API-->>U: 25 rows
```
<sub>Source: [`docs/diagrams/05-authz-sequence.mmd`](docs/diagrams/05-authz-sequence.mmd) · [SVG](docs/diagrams/05-authz-sequence.svg)</sub>

## Identity: federate, don't merge

On Day 1 we federate the acquired IdP. We don't merge directories. Toxic role combinations that only appear once groups are mapped get the **approval side quarantined**, so people keep their day job and the fraud path never goes live. Unmapped groups block the Day-100 gate.

```mermaid
flowchart LR
  subgraph ACQ["Globex on-prem AD"]
    G1["GLB-Treasury-Ops<br/>amara · ben · chen"]
    G2["GLB-Treasury-Approvers<br/>chen · dana"]
    G3["GLB-AP-Vendor<br/>eve · dana"]
    G4["GLB-Legacy-Mainframe<br/>kofi"]
  end
  subgraph MAP["Mapping (manifest)"]
    M1["→ payments_initiate"]
    M2["→ payments_approve"]
    M3["→ vendor_master_edit"]
    M4["✗ unmapped"]
  end
  G1 --> M1
  G2 --> M2
  G3 --> M3
  G4 --> M4
  M1 & M2 & M3 --> SOD{"SoD engine<br/>initiate+approve<br/>vendor+approve"}
  SOD -- "chen, dana: toxic" --> Q["QUARANTINE approval side<br/>(user keeps day job)"]
  SOD -- clean --> GR["Tenant-scoped grants<br/>northwind-globex-bank:*"]
  Q --> TKT["IGA re-certification ticket"]
  M4 --> GATE["Blocks Day 100 → 365 gate"]
  GR --> AUD[("audit")]
  Q --> AUD
```
<sub>Source: [`docs/diagrams/06-identity-federation.mmd`](docs/diagrams/06-identity-federation.mmd) · [SVG](docs/diagrams/06-identity-federation.svg)</sub>

## Network topology

```mermaid
flowchart TB
  subgraph ORG["AWS Organization"]
    subgraph CORE["Parent accounts"]
      PVPC["Parent VPCs<br/>us-east-1 · eu-west-1"]
      TGW{{"Transit Gateway"}}
      INSP["Inspection VPC<br/>NGFW · IDS · DLP"]
    end
    subgraph OU["OU: Acquisitions (SCP region lock)"]
      UFS["Umbrella Federal<br/>SILO acct · us-gov-west-1<br/>(GovCloud partition)"]
      SP["Sahel Pay<br/>SILO acct · af-south-1"]
    end
    subgraph SHARED["Shared platform account"]
      GLB["Globex Bank<br/>BRIDGE · own schema + KMS<br/>eu-west-1"]
      INI["Initech Cloud<br/>POOL · RLS rows"]
    end
  end
  PVPC --- TGW
  TGW --- INSP
  GLB -- "TGW route table → inspection only" --> INSP
  INI --- PVPC
  UFS -. "no network path" .- PVPC
  SP -. "no network path" .- PVPC
  classDef s fill:#7a1f2b,color:#fff
  classDef b fill:#8a5a00,color:#fff
  classDef p fill:#1d6b46,color:#fff
  class UFS,SP s
  class GLB b
  class INI p
```
<sub>Source: [`docs/diagrams/07-network-topology.mmd`](docs/diagrams/07-network-topology.mmd) · [SVG](docs/diagrams/07-network-topology.svg)</sub>

## Carve-out: the test of a good tenancy model

```mermaid
sequenceDiagram
  autonumber
  actor B as Board / Regulator
  participant CO as Carve-out engine
  participant REPO as TenantScopedRepo({tenant})
  participant FS as Evidence store
  participant IAM as Grants
  participant AUD as Audit chain
  B->>CO: carve_out(northwind-umbrella-federal-systems)
  CO->>REPO: query() — scope is exactly one tenant
  REPO-->>CO: 25 records
  CO->>FS: records.jsonl + sha256
  CO->>REPO: purge(tenant)
  CO->>REPO: count(tenant) == 0 ?
  CO->>IAM: revoke all grants on tenant
  CO->>FS: manifest.json (counts, hash, TSAs, clean=true)
  CO->>AUD: carveout:completed (CRITICAL)
  Note over CO,AUD: Policy R0 now denies every request to the tenant
```
<sub>Source: [`docs/diagrams/08-carveout.mmd`](docs/diagrams/08-carveout.mmd) · [SVG](docs/diagrams/08-carveout.svg)</sub>

## Live portfolio (generated by the running system)

This diagram is produced by `GET /api/hierarchy.mmd` after `make demo`. The dashboard renders it live.

```mermaid
flowchart TD
  northwind["Northwind Financial Group (parent)<br/>POOL → POOL<br/><i>integrated</i>"]:::parent
  northwind_globex_bank["Globex Bank<br/>BRIDGE → BRIDGE<br/><i>day_100</i>"]:::bridge
  northwind --> northwind_globex_bank
  northwind_initech_cloud["Initech Cloud<br/>POOL → POOL<br/><i>day_365</i>"]:::pool
  northwind --> northwind_initech_cloud
  northwind_sahel_pay["Sahel Pay<br/>SILO → SILO<br/><i>pre_close</i>"]:::silo
  northwind --> northwind_sahel_pay
  northwind_umbrella_federal_systems["Umbrella Federal Systems<br/>SILO → SILO<br/><i>carved_out</i>"]:::silo
  northwind --> northwind_umbrella_federal_systems
  classDef parent fill:#1f3a5f,color:#fff,stroke:#1f3a5f
  classDef silo fill:#7a1f2b,color:#fff,stroke:#7a1f2b
  classDef bridge fill:#8a5a00,color:#fff,stroke:#8a5a00
  classDef pool fill:#1d6b46,color:#fff,stroke:#1d6b46
```
<sub>Source: [`docs/diagrams/10-live-portfolio.mmd`](docs/diagrams/10-live-portfolio.mmd) · [SVG](docs/diagrams/10-live-portfolio.svg)</sub>

---

## Hands-on: drive it yourself

```bash
export PYTHONPATH=src MNAT_DB=my.db
python -m mnatenancy bootstrap deals/parent-northwind.json
python -m mnatenancy onboard   deals/globex-bank.json

# Pre-close: gun-jumping guard
python -m mnatenancy authorize northwind:cro     read_aggregated_financials northwind-globex-bank   # DENY R1
python -m mnatenancy authorize northwind:corpdev read_aggregated_financials northwind-globex-bank   # ALLOW (clean team)

# Close the deal and walk the gates
python -m mnatenancy gates     northwind-globex-bank
python -m mnatenancy remediate northwind-globex-bank closed true
python -m mnatenancy advance   northwind-globex-bank                        # -> day_1 (SILO)
python -m mnatenancy gates     northwind-globex-bank                        # MFA 71%, 2 criticals
python -m mnatenancy remediate northwind-globex-bank mfa_coverage_pct 94
python -m mnatenancy remediate northwind-globex-bank critical_security_findings 0
python -m mnatenancy advance   northwind-globex-bank                        # -> day_100, SILO -> BRIDGE

# Residency
python -m mnatenancy authorize northwind-globex-bank:ines read_customer_pii northwind-globex-bank --region us-east-1   # DENY R3
python -m mnatenancy authorize northwind-globex-bank:ines read_customer_pii northwind-globex-bank --region eu-west-1   # ALLOW

# TSA exit plans, CFO view, audit
python -m mnatenancy exit-plan northwind-globex-bank swift-gateway "Cut over to parent SWIFT Alliance Lite2"
python -m mnatenancy show      northwind-globex-bank
python -m mnatenancy audit --verify
python -m mnatenancy serve --port 8080
```

### HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Executive dashboard (KPIs, live hierarchy, gates, authz playground, TSA, audit) |
| GET | `/api/portfolio` | Board view: every tenant, blockers, synergy, TSA exposure, audit status |
| POST | `/api/deals` | Onboard a deal manifest (JSON body) → `201` |
| GET | `/api/tenants/{id}` | Tenant + gates + SoD + chargeback + TSAs |
| POST | `/api/tenants/{id}/advance` | Advance phase (`409` with blockers if a gate fails) |
| POST | `/api/tenants/{id}/remediate` | `{field, value}`: closed, MFA, findings, approvals |
| POST | `/api/tenants/{id}/sod/resolve` | `{principal, drop_role}` |
| POST | `/api/tenants/{id}/tsa/exit-plan` | `{service, plan}` |
| POST | `/api/tenants/{id}/carveout` | Export, purge, revoke, evidence manifest |
| POST | `/api/authorize` | `{principal, action, tenant, ctx}` → `200`/`403` + rule |
| GET | `/api/records?principal=` | Policy-scoped read via `TenantScopedRepo` |
| GET | `/api/audit`, `/api/audit/verify` | Audit trail and chain verification |
| GET | `/api/hierarchy.mmd` | Live Mermaid diagram of the tenant tree |

```bash
curl -s localhost:8080/api/portfolio | jq '.tenants[] | {name, tier, target_tier, phase, gate_ready, blockers}'
curl -s -XPOST localhost:8080/api/authorize -d '{"principal":"northwind:cro","action":"read_customer_data","tenant":"northwind-globex-bank"}'
```

### Onboard your own deal

Copy `deals/globex-bank.json` and edit it. The fields map directly to what an integration management office (IMO) already tracks: regimes, residency, headcount, app count, open critical findings, IdP, MFA coverage, pending approvals, clean-team roster, AD group → role mappings, TSAs and monthly usage.

---

## Repository map

```
src/mnatenancy/
  models.py      Tier, Phase, Intent, DealManifest, Tenant
  tiering.py     Explainable tier decision (risk score + hard constraints + convergence path)
  identity.py    Role catalogue, SoD rules, federation with quarantine
  policy.py      ABAC engine R0–R6, tenant-scope resolution
  phases.py      Gate checks, advance (tier migration + tfvars re-render), remediation
  store.py       SQLite store, TenantScopedRepo, hash-chained audit
  finance.py     Rate card, chargeback, synergy, TSA exposure
  carveout.py    Export → purge → verify zero residual → revoke → evidence manifest
  playbook.py    Manifest → tenant → landing zone → identity → TSA → audit
  service.py     Application service shared by API and CLI
  api.py         Stdlib HTTP API;  dashboard.html  live executive dashboard
  cli.py         `mnat` CLI;  demo.py  13-step scripted walkthrough
deals/           Parent + 4 acquisitions (bank, SaaS, federal contractor, Nigerian fintech)
terraform/       modules/tenant-{silo,bridge,pool} + envs/example consuming rendered tfvars
sql/             postgres_rls.sql (RLS + schema-per-bridge + append-only audit), rls_test.sql
docs/            diagrams/*.mmd + *.svg, exec-brief.md, runbook-day1.md, adr/, demo-output.txt
tests/           28 tests: tiering, gun-jumping, SoD, residency, sovereign, break-glass,
                 tenant isolation, audit tamper, carve-out, chargeback, tfvars, HTTP API
```

## From reference implementation to production

| Here | In production |
|---|---|
| SQLite + `TenantScopedRepo` | PostgreSQL with `FORCE ROW LEVEL SECURITY` (`sql/postgres_rls.sql`, tested in CI) |
| Python policy engine | Same rules in OPA/Rego or Cedar (Amazon Verified Permissions) as the PDP |
| Role catalogue in code | SailPoint / Saviynt / Entra ID Governance |
| Hash chain in a table | Same chain + periodic anchoring to S3 Object Lock / QLDB-style ledger |
| Rendered tfvars | Account Factory for Terraform / Control Tower, GitOps-applied |
| Rate card JSON | FinOps CUR data per tenant tag |

## Docs

- [Executive brief](docs/exec-brief.md): the one-pager for the board pack
- [Day-1 runbook](docs/runbook-day1.md): hour-by-hour for the IMO
- [ADR-001 Tier per deal, not per company](docs/adr/001-tier-per-deal.md)
- [ADR-002 Federate, don't merge identity](docs/adr/002-federate-identity.md)
- [ADR-003 Hash-chained audit](docs/adr/003-hash-chained-audit.md)
- [Full demo transcript](docs/demo-output.txt)

*All company names are fictional. Regulatory references are summaries for engineering design, not legal advice.*

License: Apache-2.0
