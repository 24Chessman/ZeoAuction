# Architecture decision records

We use one file per decision, based on [`0000-template.md`](0000-template.md). A record is never edited
after it's accepted. To change a decision, write a new ADR that supersedes the old one.

**Numbering.** ADR-0001 to 0008 are the eight decisions summarised in SDD §2.6. Their full records are written by
the owners in Plan 7, and until then the SDD summary is binding. ADR-0009 onwards are decisions made during implementation.

| ADR | Decision | Status | Owner | Full record due |
|---|---|---|---|---|
| [0001](0001-bid-pipeline-and-conflict-resolution.md) | Server-allocated `server_seq` determines bid order | **Accepted** | Naitik | Plan 7 (#27) |
| [0002](0002-redis-price-buffer.md) | Redis compare-and-set for current price, batched persistence | **Accepted** | Sumit / Naitik | Plan 7 (#27) |
| [0003](0003-settlement-saga-and-compensation.md) | Saga with compensations for settlement | **Accepted** | Jaydip | Plan 7 (#68) |
| [0004](0004-escrow-ledger-append-only.md) | Escrow ledger is append-only | **Accepted** | Jaydip | Plan 7 (#68) |
| [0005](0005-kyc-jwt-claim.md) | KYC status carried as a JWT claim | **Accepted** | Ayush / Sagar | Plan 7 (#49) |
| [0006](0006-escrow-sweep-cron.md) | Escrow sweep as a platform cron job | **Accepted** | Naitik / Ayush | Plan 7 (#37) |
| [0007](0007-payment-port-mock.md) | Payment behind a port with a mock adapter | **Accepted** | Jaydip | Plan 7 (#68) |
| [0008](0008-fraud-dataset-first.md) | Fraud dataset built before the detector | **Accepted** | Harshal | Plan 7 (#58) |
| [0009](0009-payment-provider.md) | Payment provider: Razorpay test mode, INR | **Accepted** (2026-10-10) | Jaydip | Plan 1 |
| [0010](0010-third-party-services.md) | Push notifications and image hosting | **Proposed** | Ayush / Gaurang | Plan 1 |
| [0011](0011-settlement-policy.md) | Settlement policy numbers (₹99 fee, window, anti-snipe) | **Accepted** (2026-10-10) | Jaydip / Sumit | Plan 1 |
| [0012](0012-repository-and-platform-conventions.md) | Monorepo, service template, schema-per-service | **Proposed** | Ayush | Plan 1 |
| [0013](0013-aadhaar-secure-qr-and-face-match.md) | Seller KYC by Aadhaar Secure QR and a live face match | **Proposed** | Sagar | 2026-10-20 |

A Proposed ADR becomes Accepted when it's approved at the end-of-plan review, with at least two approvals on its PR.
