-- Schema: dispute — Dispute Management (owner: Jay)
-- SDD 4.3.3, 5.2.4, 6.6, 7.5, 7.6. Dispute states: docs/state-machines.md (Dispute).

CREATE TABLE dispute.disputes (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id          uuid NOT NULL,                  -- payment.orders.id
  opened_by         text NOT NULL CHECK (opened_by IN ('BUYER', 'FRAUD_SERVICE')),
  opened_by_user_id uuid,                           -- null when opened by the fraud service
  fraud_alert_id    uuid,                           -- fraud.fraud_alerts.alert_id (FR-DISP-6)
  reason_code       text NOT NULL CHECK (reason_code IN (
                      'ITEM_NOT_RECEIVED', 'NOT_AS_DESCRIBED', 'DAMAGED_IN_TRANSIT',
                      'COUNTERFEIT', 'SUSPECTED_FRAUD', 'OTHER')),
  description       text NOT NULL CHECK (length(description) <= 4000),
  state             text NOT NULL DEFAULT 'OPEN' CHECK (state IN (
                      'OPEN', 'UNDER_REVIEW', 'RESOLVED_SELLER', 'RESOLVED_BUYER')),
  fault             text CHECK (fault IN ('BUYER', 'SELLER', 'PLATFORM')),
  resolution_note   text,
  resolved_by       uuid,
  resolved_at       timestamptz,
  opened_at         timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK ((opened_by = 'BUYER') = (opened_by_user_id IS NOT NULL)),
  CHECK (opened_by <> 'FRAUD_SERVICE' OR fraud_alert_id IS NOT NULL),
  -- Fault is required for a buyer-favourable outcome; it drives the fee treatment (FR-PAY-9).
  CHECK (state <> 'RESOLVED_BUYER' OR fault IS NOT NULL),
  CHECK ((state IN ('RESOLVED_SELLER', 'RESOLVED_BUYER')) = (resolved_at IS NOT NULL))
);

-- At most one unresolved dispute per order.
CREATE UNIQUE INDEX disputes_one_open_per_order
  ON dispute.disputes (order_id) WHERE state IN ('OPEN', 'UNDER_REVIEW');

CREATE TRIGGER disputes_touch BEFORE UPDATE ON dispute.disputes
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- Evidence: an uploaded photo or document (object key), or a linked bid trace (fraud cases).
CREATE TABLE dispute.dispute_evidence (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dispute_id    uuid NOT NULL REFERENCES dispute.disputes (id),
  kind          text NOT NULL CHECK (kind IN ('PHOTO', 'DOCUMENT', 'BID_TRACE', 'SELLER_RESPONSE')),
  object_key    text CHECK (object_key IS NULL OR object_key !~ '^[a-z]+://'),
  bid_trace     jsonb,
  body          text,
  submitted_by  uuid,
  submitted_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (
       (kind IN ('PHOTO', 'DOCUMENT') AND object_key IS NOT NULL)
    OR (kind = 'BID_TRACE' AND bid_trace IS NOT NULL)
    OR (kind = 'SELLER_RESPONSE' AND body IS NOT NULL))
);

CREATE INDEX dispute_evidence_dispute_idx ON dispute.dispute_evidence (dispute_id);

GRANT SELECT, INSERT, UPDATE ON dispute.disputes TO dispute_svc;
GRANT SELECT, INSERT ON dispute.dispute_evidence TO dispute_svc;
