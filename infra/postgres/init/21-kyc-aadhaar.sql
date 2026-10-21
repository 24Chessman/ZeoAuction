-- Schema: kyc — Aadhaar Secure QR and the live face check (owner: Sagar)
-- Replaces document upload (GOVERNMENT_ID / PROOF_OF_ADDRESS / SELFIE in 20-kyc.sql).
-- Flow and transitions: services/kyc/README.md, docs/state-machines.md section 3, ADR-0013.

-- A submission now keeps two images: the photo from the signed QR (re-encoded as JPEG) and
-- the best live frame of a face check that matched or went to review.
ALTER TABLE kyc.kyc_documents DROP CONSTRAINT kyc_documents_doc_type_check;
ALTER TABLE kyc.kyc_documents ADD CONSTRAINT kyc_documents_doc_type_check
  CHECK (doc_type IN ('AADHAAR_PHOTO', 'FACE_CAPTURE'));
CREATE UNIQUE INDEX kyc_documents_one_per_type
  ON kyc.kyc_documents (submission_id, doc_type);

-- What the verified Secure QR said, minus what must not be kept: no Aadhaar number (only
-- the last four digits UIDAI itself puts in referenceId), no address beyond state and PIN
-- code, no QR payload, no mobile digits or hashes. One row per submission, written with it
-- (K1/K5) and never changed.
CREATE TABLE kyc.aadhaar_verifications (
  submission_id        uuid PRIMARY KEY REFERENCES kyc.kyc_submissions (id),
  reference_last4      char(4) NOT NULL CHECK (reference_last4 ~ '^[0-9]{4}$'),
  qr_generated_at      timestamptz NOT NULL,  -- referenceId timestamp: when UIDAI made the QR
  signer_sha256        text NOT NULL,        -- the trusted certificate the signature verified with
  holder_name          text NOT NULL,
  year_of_birth        smallint NOT NULL,
  gender               char(1) NOT NULL CHECK (gender IN ('M', 'F', 'T')),
  state                text,
  pincode              text CHECK (pincode ~ '^[0-9]{6}$'),
  mobile_verified      boolean,              -- NULL: the seller gave no number to check
  face_model           text NOT NULL,
  reference_faces      smallint NOT NULL,    -- faces found in the Aadhaar photo; 1 = usable
  reference_embedding  real[],               -- face template of that photo; NULL if unusable
  verified_at          timestamptz NOT NULL,
  CHECK ((reference_faces = 1) = (reference_embedding IS NOT NULL))
);

-- Every face check, matched or not. Append-only: NO_MATCH and LIVENESS_FAILED rows count
-- towards the attempt limit, so they are never rewritten.
CREATE TABLE kyc.face_match_attempts (
  id             bigserial PRIMARY KEY,
  submission_id  uuid NOT NULL REFERENCES kyc.kyc_submissions (id),
  attempt_no     smallint NOT NULL CHECK (attempt_no > 0),
  frames         smallint NOT NULL CHECK (frames > 0),
  good_frames    smallint NOT NULL CHECK (good_frames >= 0 AND good_frames <= frames),
  median_score   real,
  min_score      real,
  yaw_span       real,
  outcome        text NOT NULL CHECK (outcome IN (
                   'MATCH', 'REVIEW', 'NO_MATCH', 'LIVENESS_FAILED', 'NO_FACE')),
  at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (submission_id, attempt_no)       -- two checks sent at once: one of them loses
);

CREATE TRIGGER face_match_attempts_append_only BEFORE UPDATE OR DELETE ON kyc.face_match_attempts
  FOR EACH ROW EXECUTE FUNCTION public.forbid_update_delete();

GRANT SELECT, INSERT ON kyc.aadhaar_verifications TO kyc_svc;
GRANT SELECT, INSERT ON kyc.face_match_attempts TO kyc_svc;
GRANT USAGE ON SEQUENCE kyc.face_match_attempts_id_seq TO kyc_svc;
