# Day-1 runbook (legal close)

| T | Owner | Action | Command / evidence |
|---|---|---|---|
| T-30d | Corp Dev | Deal manifest complete; clean-team roster signed by counsel | `deals/<target>.json` |
| T-30d | Platform | Onboard as PRE_CLOSE; landing zone rendered and planned | `mnat onboard ...`; `terraform plan` |
| T-7d | IGA | Review identity report: unmapped groups, SoD, privileged users | `mnat show <tenant>` → `identity` |
| T-0 | Legal | Confirm close and regulatory clearance | `mnat remediate <t> closed true` |
| T+0h | IMO | Advance to DAY_1 (clean team auto-dissolved, audited) | `mnat advance <t>` |
| T+1h | Platform | `terraform apply` the SILO/BRIDGE landing zone | CI artifact `out/terraform/` |
| T+2h | IGA | Federation live; quarantined SoD roles ticketed for re-cert | audit `identity:federated` |
| T+4h | Finance | Consolidation read access verified for parent CFO | `mnat authorize northwind:cfo read_aggregated_financials <t>` |
| T+8h | CISO | Break-glass path tested and logged | `mnat authorize northwind:ciso admin_infrastructure <t> --break-glass "..."` |
| T+24h | Audit | Chain verified; evidence pack exported | `mnat audit --verify` |
| Daily | IMO | Gate review until Day 100 | `mnat gates <t>` / dashboard |

**Never on Day 1:** merge directories, peer networks flat, pool regulated data, or grant parent admins standing access to a SILO.
