# Architecture decision records

We use one file per decision, based on [`0000-template.md`](0000-template.md). A record is never edited
after it's accepted. To change a decision, write a new ADR that supersedes the old one.

**Numbering.** ADR-0001 to 0008 are the eight decisions summarised in SDD §2.6. Their full records are written by
the owners in Plan 7, and until then the SDD summary is binding. ADR-0009 onwards are decisions made during implementation.

| ADR | Decision | Status | Owner | Full record due |
|---|---|---|---|---|
| 0001 | Server-allocated `server_seq` determines bid order | Accepted (SDD) | Naitik | Plan 7 (#27) |
| 0002 | Redis compare-and-set for current price, batched persistence | Accepted (SDD) | Sumit / Naitik | Plan 7 (#27) |
| 0003 | Saga with compensations for settlement | Accepted (SDD) | Jaydip | Plan 7 (#68) |
| 0004 | Escrow ledger is append-only | Accepted (SDD) | Jaydip | Plan 7 (#68) |
| 0005 | KYC status carried as a JWT claim | Accepted (SDD) | Ayush / Sagar | Plan 7 (#49) |
| 0006 | Escrow sweep as a platform cron job | Accepted (SDD) | Naitik / Ayush | Plan 7 (#37) |
| 0007 | Payment behind a port with a mock adapter | Accepted (SDD) | Jaydip | Plan 7 (#68) |
| 0008 | Fraud dataset built before the detector | Accepted (SDD) | Harshal | Plan 7 (#58) |
| [0009](0009-payment-provider.md) | Payment provider: Razorpay test mode, INR | **Accepted** (2026-10-10) | Jaydip | Plan 1 |
| [0010](0010-third-party-services.md) | Push notifications and image hosting | **Proposed** | Ayush / Gaurang | Plan 1 |
| [0011](0011-settlement-policy.md) | Settlement policy numbers (₹99 fee, window, anti-snipe) | **Accepted** (2026-10-10) | Jaydip / Sumit | Plan 1 |
| [0012](0012-repository-and-platform-conventions.md) | Monorepo, service template, schema-per-service | **Proposed** | Ayush | Plan 1 |

A Proposed ADR becomes Accepted when it's approved at the end-of-plan review, with at least two approvals on its PR.
