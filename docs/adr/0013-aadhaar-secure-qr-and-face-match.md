# ADR-0013: Seller KYC by Aadhaar Secure QR and a live face match

| | |
|---|---|
| **Status** | **Proposed**: implemented in the working tree 2026-10-20 (offline XML), revised the same day to the Secure QR; ratify at the next end-of-plan review |
| **Date** | 2026-10-20 |
| **Owners** | Sagar (KYC) |
| **Requirements** | FR-KYC-1..3, FR-DOC-4, NFR-SEC-2; SDD 4.2.1, 6.3, 8.4, 8.8. Supersedes the document-upload flow of `services/kyc/docs/design.md` |

## Context

Plan 3 verified sellers by having them upload a government ID and a proof of address, which an administrator
opened and judged by eye. That flow can't tell a forged scan from a real one, puts every seller in a manual queue,
and makes us store identity documents we can't check.

Every Aadhaar letter, e-Aadhaar PDF and PVC card printed since 2019 carries a **Secure QR code**
([UIDAI](https://uidai.gov.in/en/ecosystem/authentication-devices-documents/qr-code-reader.html)): name, date of birth,
gender, address, a photo, the last 4 digits of the Aadhaar and of the mobile (V2) or mobile/email hashes (2019 layout),
GZip-compressed and **signed by UIDAI** (RSA-2048, SHA-256). Reading it needs no AUA/KUA licence and nothing from the
holder beyond a photo of a card they already have.

The first version of this ADR used the **Paperless Offline e-KYC** XML instead (a ZIP behind a share code, downloaded
from myAadhaar). It was replaced the same day: sellers had to log in to UIDAI, download a file and type a share code, and
the XML had to be under 72 h old, whereas a photo of the QR they already own works in seconds.

## Decision

1. **The Aadhaar Secure QR replaces document upload.** The seller uploads a photo of the QR. The KYC service reads it
   with **zxing-cpp** (the maintained C++ port of Google's ZXing, Apache-2.0; wheels for every platform, no system
   library, robust on dense, tilted, unevenly lit codes), inflates the payload, and verifies UIDAI's signature over
   it against configured certificates only (the QR carries no key). The seller must be 18 or over. The optional
   mobile check compares the last 4 digits (V2) or UIDAI's hash (2019 layout). There is no age limit on the QR by
   default (a card's QR dates from when it was printed); `KYC_AADHAAR_MAX_AGE_HOURS` can demand a fresh e-Aadhaar.
2. **A live face match decides the case.** The browser captures guided frames (straight, left, right). The server
   matches them to the QR's photo with **OpenCV YuNet + SFace** (Apache-2.0 models from the OpenCV zoo, CPU only, no
   network calls) and requires a head turn as basic liveness. A match (clear or close) goes to the administrator
   queue, and an administrator approves every seller (changed 2026-10-22; a clear match used to verify on its own);
   three failures reject, with a 24 h cooldown before trying again.
3. **States stay the same.** `SUBMITTED` now means "Aadhaar verified, face check pending", and `UNDER_REVIEW` means
   "referred by the face check". The `auth.users.kyc_status` vocabulary, CT-2 and the listing gate don't change.
   Admin `start-review` (old K2) is removed; K2 is now the face check's referral.
4. **Data minimisation.** Kept: name, birth year, gender, state, PIN, last 4 digits, the XML timestamp, the signer
   fingerprint, the face template, the Aadhaar photo and one matched frame (encrypted bucket). Never kept: the
   QR photo or payload, the mobile number, the full address, failed frames.

### Alternatives considered

| Option | Why not |
|---|---|
| `face_recognition` (dlib) | Needs a C++ toolchain to build on Windows; heavier install for every member |
| DeepFace / InsightFace | TensorFlow or large models; InsightFace's pretrained models are non-commercial |
| A cloud face API | Sends biometric data to a third party; against NFR-SEC-2 and ADR-0010's direction |
| Online Aadhaar e-KYC (OTP via AUA/KUA) | Needs a licensed AUA/KUA; not available to a student project |
| Paperless Offline e-KYC XML (this ADR's first version) | Portal login, download and share code for every seller; 72 h freshness |
| pyzbar (ZBar) or OpenCV's `QRCodeDetector` for the QR | ZBar needs a system library on Linux and is barely maintained; OpenCV's detector is weaker on dense codes in phone photos |

## Consequences

- Every seller passes through the admin queue after the face check; the attempt's outcome (`MATCH` or `REVIEW`) tells the reviewer how confident the check was.
- The KYC image grows by OpenCV (~60 MB) and the models (~39 MB, fetched and checksummed at build time).
- The face template and photos are biometric data: the retention ADR (#49) must cover them, and the purge job
  (Plan 6) must delete `aadhaar_verifications.reference_embedding` with the images.
- Thresholds (0.42 / 0.30) were checked on sample images only; they must be tuned on consented captures.
- The liveness check stops a still photo, not a video replay or a mask; the demo says so.
- Real Secure QR verification hasn't been run against a real Aadhaar here yet. The layout follows UIDAI's QR user
  manual and two open-source readers (pyaadhaar, Anon Aadhaar); it is tested with synthetic QRs signed the same way
  (`services/kyc/scripts/synthetic_qr.py`). The bundled certificate is UIDAI's current one
  (`uidai_offline_publickey_2026.cer`, valid to 2029-02-03); QRs signed before February 2026 by an older UIDAI key
  need that certificate added (`KYC_EXTRA_TRUSTED_CERTS`). Try one real card before the demo.
- A QR proves the card is genuine, not that the uploader owns it; the face match is what ties the two.
- Schema change: `infra/postgres/init/21-kyc-aadhaar.sql` (new tables; document types become `AADHAAR_PHOTO`,
  `FACE_CAPTURE`). Errors: `contracts/errors/kyc-error-codes.yaml`.
