-- Schema: fraud — Fraud Detection (owner: Harshal)
-- SDD 4.3.3, 5.4. Alerts are also published to the fraud.alerts topic (ShillAlert v1).

CREATE TABLE fraud.fraud_alerts (
  alert_id           uuid PRIMARY KEY,
  auction_id         uuid NOT NULL,
  ring_id            uuid,
  score              numeric(5, 4) NOT NULL CHECK (score BETWEEN 0 AND 1),
  signals            jsonb NOT NULL,
  raised_at          timestamptz NOT NULL,
  auction_closes_at  timestamptz NOT NULL,
  -- Linked when the alert opens a dispute (FR-DISP-6).
  dispute_id         uuid,
  -- AC-14: an alert raised at or after close is a miss, and is recorded as one.
  raised_before_close boolean GENERATED ALWAYS AS (raised_at < auction_closes_at) STORED
);

CREATE INDEX fraud_alerts_auction_idx ON fraud.fraud_alerts (auction_id);

-- Results of each scoring run against the labelled synthetic dataset (ADR-0008).
CREATE TABLE fraud.evaluation_runs (
  id               bigserial PRIMARY KEY,
  dataset_version  text NOT NULL,
  detector_version text NOT NULL,
  threshold        numeric(5, 4) NOT NULL,
  recall           numeric(5, 4) NOT NULL,
  precision        numeric(5, 4) NOT NULL,
  late_alerts      integer NOT NULL DEFAULT 0,
  run_at           timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON fraud.fraud_alerts TO fraud_svc;
GRANT SELECT, INSERT ON fraud.evaluation_runs TO fraud_svc;
GRANT USAGE ON SEQUENCE fraud.evaluation_runs_id_seq TO fraud_svc;
