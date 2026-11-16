# KYC

ZeoAuction's KYC service verifies Aadhaar Secure QR photos and sends every
successful submission directly to administrator review. Face matching and
webcam capture are not part of this service.

## Seller routes

| Method and path | Purpose |
|---|---|
| `POST /api/v1/kyc/aadhaar` | Upload `qr_image` (JPEG/PNG/WebP, up to 8 MB) and optionally provide `mobile`. A verified QR creates an `UNDER_REVIEW` submission. |
| `GET /api/v1/kyc/submissions/me` | Return the seller's latest submission, Aadhaar summary, state, and document metadata. |

The QR reader validates the UIDAI signature, bounded payload, holder details,
age, optional mobile number, and embedded photo. Only the Aadhaar summary and
the re-encoded photo are retained; the original QR payload and mobile number
are not stored.

## Admin routes

All routes require the `ADMIN` role:

| Method and path | Purpose |
|---|---|
| `GET /api/v1/admin/kyc/queue?state=UNDER_REVIEW&limit&offset` | List Aadhaar submissions waiting for review, oldest first. |
| `GET /api/v1/admin/kyc/{id}` | View the submission, Aadhaar summary, and document metadata. |
| `POST /api/v1/admin/kyc/{id}/approve` | Approve the seller (`VERIFIED`). |
| `POST /api/v1/admin/kyc/{id}/reject` | Reject with a reason; the seller may submit a new QR. |
| `POST /api/v1/admin/kyc/{id}/suspend` | Suspend a verified seller. |
| `POST /api/v1/admin/kyc/{id}/reinstate` | Reinstate a suspended seller. |
| `GET /api/v1/admin/kyc/{id}/documents/{doc_id}/url` | Issue a short-lived, audited signed URL. |

Approval and rejection update the `auth.users.kyc_status` mirror and publish a
token-version change. Sellers must refresh their token before the new status
is used by other services.

## Configuration

| Variable | Meaning |
|---|---|
| `KYC_REPOSITORY` | `postgres` or `memory` |
| `KYC_STORAGE` | `s3` or `memory` |
| `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL` | S3-compatible storage endpoints |
| `KYC_SIGNED_URL_TTL_SECONDS` | Signed URL lifetime, capped at 300 seconds |
| `KYC_RETENTION_DAYS` | Document retention period |
| `KYC_EXTRA_TRUSTED_CERTS` | Optional development-only UIDAI certificates |
| `KYC_AADHAAR_MAX_AGE_HOURS` | QR age limit; `0` disables the limit |

## Running

```powershell
docker compose up -d kyc
Push-Location services\kyc
..\..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

For local demos, use `services/kyc/scripts/synthetic_qr.py` to generate a
development-signed QR. Never configure development certificates on a hosted
environment.
