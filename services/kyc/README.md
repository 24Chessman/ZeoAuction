# kyc

| | |
|---|---|
| **Component** | KYC & Seller Verification |
| **Interface owner** | Sagar |
| **Kind** | HTTP API service |
| **Owns schema** | `kyc` (database role `kyc_svc`); writes the `auth.users` claim mirror and appends to `admin.audit_log` (documented exceptions) |
| **Design** | SDD 4.2.1, 6.3, 6.7, 8.4, 8.8; [ADR-0013](../../docs/adr/0013-aadhaar-secure-qr-and-face-match.md); CT-2 `contracts/openapi/internal/kyc-status.v1.yaml`; errors `contracts/errors/kyc-error-codes.yaml` |
| **History** | Plan 3 shipped document upload + admin review ([`docs/design.md`](docs/design.md), superseded). Replaced 2026-10-20 by Aadhaar e-KYC + live face match; the offline XML became the Secure QR the same day |

## Responsibility

A seller proves who they are in two steps, and the service decides most cases on its own:

1. **Aadhaar Secure QR** ([UIDAI](https://uidai.gov.in/en/ecosystem/authentication-devices-documents/qr-code-reader.html)).
   The seller uploads a photo of the QR on their Aadhaar letter, PVC card or e-Aadhaar. The service reads it with
   zxing-cpp (`app/adapters/qr_reader.py`), checks UIDAI's signature, and keeps only a summary.
2. **Live face check.** The browser takes 6 guided webcam frames (straight, left, right). The service matches
   them against the photo in the QR with OpenCV (YuNet detection + SFace recognition) and checks that the head
   turned (basic liveness).

It also owns the verification state machine (`docs/state-machines.md` §3) and the `kyc_status` claim mirror.
The listing gate itself runs in Auction Orchestration and reads the JWT claim (CT-2), so no listing request
calls this service.

### Seller routes (bearer token)

| Method and path | Purpose |
|---|---|
| `POST /api/v1/kyc/aadhaar` | Multipart `qr_image` (JPEG/PNG/WebP, ≤ 8 MB), optional `mobile`. A verified QR creates the submission in `SUBMITTED` (K1, or K5 after a rejection). Re-uploading while `SUBMITTED` with no counted face attempt replaces the waiting row (K4b) |
| `POST /api/v1/kyc/submissions/{id}/face` | Multipart `frames` (3–8 JPEG/PNG, ≤ 2 MB each). Returns `{outcome, attempts_left, submission}` and may move the submission (K2, K3a, K4a) |
| `GET /api/v1/kyc/submissions/me` | Latest submission: state, reason, `can_resubmit`, `resubmit_after`, Aadhaar summary, face attempts left, image metadata. Never a URL |

### What the Aadhaar check verifies (`app/domain/aadhaar.py`)

The QR's text is one decimal number; as big-endian bytes it is a GZip stream. Inflated, it holds `0xFF`-separated
fields (an optional `V2` marker, the email/mobile indicator, `referenceId` = last 4 digits + IST timestamp, name, dob,
gender, address fields, and in V2 the mobile's last 4 digits), then the JPEG 2000 photo, then (2019 layout only) the
email and mobile hashes, then a 256-byte RSA signature over everything before it.

In order; the first failure is `422 AADHAAR_INVALID` with `details.reason` and `details.field` (`qr_image` unless noted):

| Check | Reason |
|---|---|
| A JPEG, PNG or WebP (magic bytes), ≤ 8 MB, that OpenCV can decode | `not_image`, `too_large` |
| zxing-cpp finds a QR code (photos over 4000 px are scaled down first) | `no_qr` |
| Its text is a decimal number that inflates as GZip (the pre-2019 QR is plain, unsigned XML) | `not_secure_qr` |
| At most 7089 digits, inflates to ≤ 64 KB (bounded, no zip bomb), complete stream | `malformed_qr` |
| RSA PKCS#1 v1.5 SHA-256 signature over all but the last 256 bytes, by a **configured** certificate | `signature_invalid` |
| All fields present, indicator 0–3, valid `referenceId` | `malformed_qr` |
| Timestamp not in the future; not older than `KYC_AADHAAR_MAX_AGE_HOURS` when set (off by default) | `from_future`, `stale` |
| Name, gender (M/F/T), date or year of birth; **18 or older** (year only: assumes 31 Dec); JPEG 2000 photo | `malformed_qr`, `underage`, `no_photo` |
| Optional mobile: V2 compares the last 4 digits; the 2019 layout compares `sha256` repeated *last Aadhaar digit* times (once for 0 and 1) | `mobile_mismatch` (field `mobile`) |

If the photo shows several QR codes (an e-Aadhaar page), the first that verifies wins.

### The face decision (`app/domain/face.py`)

| Outcome | When | Effect |
|---|---|---|
| `MATCH` | median similarity ≥ 0.42 and every frame ≥ 0.30, head turned | K3a → `VERIFIED`; best frame kept |
| `REVIEW` | median ≥ 0.30, or no usable face in the Aadhaar photo | K2 → `UNDER_REVIEW`; best frame kept for the admin |
| `NO_MATCH` | median < 0.30 | counts; the 3rd counted failure is K4a → `REJECTED` |
| `LIVENESS_FAILED` | duplicate frames, or yaw span < 0.12 | counts |
| `NO_FACE` | fewer than 3 frames with exactly one face | **doesn't count** (lighting, framing) |

After K4a a new upload is refused with `409 KYC_COOLDOWN` (`details.retry_after`) for 24 h, so failed matches
can't be retried endlessly. Thresholds are for SFace cosine similarity (OpenCV's own same-person threshold is
0.363 on good photos). Measured on OpenCV's sample images: a 1.3 KB JPEG 2000 crop of one face scored 0.51–0.58
against full-size frames of the same face and 0.16–0.19 against another person. **Tune on consented real
captures before relying on it**, via the `KYC_FACE_*` settings. The liveness check is basic: it stops a still
photo held up to the camera, not a video replay or a mask.

### Admin routes (role `ADMIN`)

| Method and path | Transition |
|---|---|
| `GET /api/v1/admin/kyc/queue?state=UNDER_REVIEW&limit&offset` | Face-check referrals, oldest first (`state=SUBMITTED` lists sellers mid-flow) |
| `GET /api/v1/admin/kyc/{id}` | Submission, Aadhaar summary (with PIN, signer fingerprint, faces in the photo), every face attempt with scores, image metadata |
| `POST /api/v1/admin/kyc/{id}/approve` | K3 |
| `POST /api/v1/admin/kyc/{id}/reject` `{reason}` (10–500 chars) | K4; the reason is shown to the seller |
| `POST /api/v1/admin/kyc/{id}/suspend` `{reason_code}` | K6 |
| `POST /api/v1/admin/kyc/{id}/reinstate` | K7 |
| `GET /api/v1/admin/kyc/{id}/documents/{doc_id}/url` | `{url, expires_in: 60}`, a fresh signed URL per view, `Cache-Control: no-store`; **the view is audited** (`KYC_DOC_VIEW`) |

`start-review` is gone: the face check moves a close match to `UNDER_REVIEW` itself. Anything outside the table
is `409 CONFLICT` with `details.state`. A race is caught by `UPDATE … WHERE state = $from` (transitions) and by
`UNIQUE (submission_id, attempt_no)` (two face checks at once).

### What one transition writes (one database transaction)

1. `kyc_submissions` with the expected-state check (plus, for a face check, the `face_match_attempts` row and the kept frame);
2. a row in the append-only `kyc_state_transitions`;
3. `auth.users.kyc_status` plus `token_version + 1`;
4. `admin.audit_log` for admin actions.

After the commit, the new `token_version` is published to Redis as `tv:{user_id}`; the listing gate refuses older
tokens with `401 TOKEN_STALE`, so a verification takes effect on the seller's next refreshed token.

### Privacy (NFR-SEC-2)

Kept (`kyc.aadhaar_verifications`, `21-kyc-aadhaar.sql`): name, birth year, gender, state, PIN code, the last 4
digits UIDAI itself puts in `referenceId`, the QR's timestamp, the signer fingerprint, whether the mobile matched,
and the SFace template of the Aadhaar photo. Images (private, SSE-S3 `kyc-documents` bucket): the Aadhaar photo
re-encoded as JPEG, and one frame of a check that matched or went to review. **Never kept or logged:** the QR
photo, the QR payload, the mobile number, the full address, failed frames. Logs carry ids only. Use synthetic QRs
(`scripts/synthetic_qr.py`) or your own Aadhaar with consent; never someone else's.

## Running it

The face models are not committed (SFace is 38 MB). The Docker image fetches them at build time; locally:

```bash
python services/kyc/scripts/fetch_face_models.py        # -> services/kyc/models/, checksums verified
```

A real Secure QR is signed by UIDAI and verifies against the bundled certificate
(`app/certs/uidai_offline_publickey_2026.cer`, "DS Unique Identification Authority of India 06", valid 2026-02-03
to 2029-02-03, from UIDAI's [Data and Downloads](https://uidai.gov.in/en/data-and-download) page; only its key is
used). **It hasn't been tried against a real Aadhaar here yet**; do that once before the demo. A QR printed before
February 2026 may be signed by an older UIDAI key (`uidai_offline_publickey_17022026.cer` or `_26022021.cer` on the
same page); if such a card fails with `signature_invalid`, add that certificate with `KYC_EXTRA_TRUSTED_CERTS`. For demos without real data,
make a synthetic QR signed with a dev key:

```bash
python services/kyc/scripts/synthetic_qr.py --photo me.jpg --name "Asha Verma" --dob 14-02-1998 \
    --mobile 9876543210 --out asha-qr.png        # --layout 1 for the 2019 layout
# then in the root .env (Compose mounts services/kyc/dev-certs at /srv/dev-certs):
KYC_EXTRA_TRUSTED_CERTS=/srv/dev-certs/dev-secure-qr.cer
```

Upload the PNG, or a phone photo of it on screen.

Never set `KYC_EXTRA_TRUSTED_CERTS` on a hosted environment.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `KYC_REPOSITORY` | `postgres` | `memory` runs without a database |
| `KYC_STORAGE` | `s3` | `memory` keeps images in process |
| `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL` | `http://localhost:8333` | Where the service writes, and the host signed URLs point at |
| `KYC_SIGNED_URL_TTL_SECONDS` | `60` | Capped at 300 by `zeo_common.storage` |
| `KYC_RETENTION_DAYS` | `365` | Sets `purge_after` until the retention ADR decides (FR-DOC-4) |
| `KYC_EXTRA_TRUSTED_CERTS` | empty | Comma-separated extra certificates (dev only) |
| `KYC_AADHAAR_MAX_AGE_HOURS` | `0` | Oldest QR accepted, by its `referenceId` timestamp; `0` = no limit |
| `KYC_FACE_MODELS_DIR` | `services/kyc/models` (`/srv/models` in Docker) | YuNet + SFace ONNX files |
| `KYC_FACE_MATCH_THRESHOLD` / `KYC_FACE_REVIEW_THRESHOLD` | `0.42` / `0.30` | SFace cosine similarity |
| `KYC_FACE_MIN_YAW_SPAN` | `0.12` | Head turn needed across frames |
| `KYC_FACE_MAX_ATTEMPTS` / `KYC_FACE_COOLDOWN_HOURS` | `3` / `24` | Counted failures before K4a, wait before a new upload |
| `KYC_MAX_FRAME_BYTES` | `2097152` | Per camera frame |

## Run

```bash
docker compose up -d kyc          # as part of the stack (fresh DB needed for 21-kyc-aadhaar.sql)
cd services/kyc && pytest         # unit tests; the OpenCV checks skip unless the models were fetched
```
