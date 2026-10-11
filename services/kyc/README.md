# kyc

| | |
|---|---|
| **Component** | KYC & Seller Verification |
| **Interface owner** | Sagar |
| **Kind** | HTTP API service |
| **Owns schema** | `kyc` (database role `kyc_svc`); writes the `auth.users` claim mirror and appends to `admin.audit_log` (documented exceptions) |
| **Design** | SDD 4.2.1, 6.3, 6.7, 8.4, 8.8; [`docs/design.md`](docs/design.md); CT-2 `contracts/openapi/internal/kyc-status.v1.yaml` |
| **Plan 3** | #38 submission API, #39 document store, #40 verification state machine, #80 admin review queue (Jay) |

## Responsibility

Seller document submission, the encrypted document store, the verification state machine (K1–K7 in
`docs/state-machines.md` §3), and the `kyc_status` claim mirror. The listing gate itself runs in Auction
Orchestration and reads the JWT claim (CT-2), so no listing request calls this service.

### Seller routes (bearer token)

| Method and path | Purpose |
|---|---|
| `POST /api/v1/kyc/submissions` | Multipart `government_id`, `proof_of_address`, optional `selfie`. K1, or K5 after a rejection (a new row; the rejected one stays for audit). `409 KYC_ALREADY_ACTIVE` while a live submission exists |
| `POST /api/v1/kyc/submissions/{id}/documents` | Add a document type the submission lacks (form `doc_type` + `file`) while it is still `SUBMITTED` |
| `GET /api/v1/kyc/submissions/me` | Latest submission: state, rejection reason, `can_resubmit`, document metadata. Never a URL |

Documents: JPEG, PNG or PDF, **sniffed from the bytes** (the upload header is only cross-checked), at most 10 MB, one per type.
A refused document is `422 DOCUMENT_INVALID` with `details.reason` (`unknown_type`, `empty`, `too_large`,
`unsupported_format`, `mime_mismatch`, `missing`, `duplicate_type`). Object keys are
`kyc/{user_id}/{submission_id}/{doc_type}-{doc_id}.{ext}`: ids only, never a file name.

### Admin routes (role `ADMIN`)

| Method and path | Transition |
|---|---|
| `GET /api/v1/admin/kyc/queue?state=SUBMITTED&state=UNDER_REVIEW&limit&offset` | Waiting submissions, oldest first |
| `GET /api/v1/admin/kyc/{id}` | Submission with document metadata and SHA-256 |
| `POST /api/v1/admin/kyc/{id}/start-review` | K2 |
| `POST /api/v1/admin/kyc/{id}/approve` | K3 |
| `POST /api/v1/admin/kyc/{id}/reject` `{reason}` (10–500 chars) | K4; the reason is shown to the seller |
| `POST /api/v1/admin/kyc/{id}/suspend` `{reason_code}` | K6 |
| `POST /api/v1/admin/kyc/{id}/reinstate` | K7 |
| `GET /api/v1/admin/kyc/{id}/documents/{doc_id}/url` | `{url, expires_in: 60}`, a fresh signed URL per view, `Cache-Control: no-store`; **the view is audited** (`KYC_DOC_VIEW`) |

Anything outside the table is `409 CONFLICT` with `details.state`, and nothing changes. A race between two admins
is caught by `UPDATE … WHERE state = $from`.

### What one transition writes (one database transaction)

1. `kyc_submissions` with the expected-state check;
2. a row in the append-only `kyc_state_transitions` (actor, reason, timestamp);
3. `auth.users.kyc_status` plus `token_version + 1`;
4. `admin.audit_log` for admin actions.

After the commit, the new `token_version` is published to Redis as `tv:{user_id}`. The listing gate
(`zeo_common.gateway.VerifiedSeller`) refuses older tokens with `401` `details.reason = TOKEN_STALE`, so an approval
or a suspension takes effect on the seller's next refreshed token instead of after up to 15 minutes.

**Privacy (NFR-SEC-2):** bytes go only to the private, SSE-S3-encrypted `kyc-documents` bucket. Logs carry ids only,
never bytes, URLs or file names. Use synthetic or consented sample documents only.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `KYC_REPOSITORY` | `postgres` | `memory` runs without a database |
| `KYC_STORAGE` | `s3` | `memory` keeps documents in process |
| `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL` | `http://localhost:8333` | Where the service writes, and the host signed URLs point at (the browser's view) |
| `KYC_SIGNED_URL_TTL_SECONDS` | `60` | Capped at 300 by `zeo_common.storage` |
| `KYC_RETENTION_DAYS` | `365` | Sets `purge_after` until the retention ADR decides (FR-DOC-4) |

## Run

```bash
docker compose up -d kyc          # as part of the stack
cd services/kyc && pytest         # unit tests (after installing libs/zeo-common)
```
