-- Schema: notify — notification history behind the WebSocket tray (owner: Ayush)
-- SDD 7.2 (GET /api/v1/notifications), 7.8, 8.9. Live delivery is over the WebSocket
-- "notification" message; this table serves the history and unread count.

CREATE TABLE notify.notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL,
  type        text NOT NULL CHECK (type IN (
                'OUTBID', 'KYC_STATUS', 'DISPUTE', 'PAYOUT', 'AUCTION_WON', 'BROADCAST')),
  payload     jsonb NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  read_at     timestamptz
);

CREATE INDEX notifications_user_idx ON notify.notifications (user_id, created_at DESC);

GRANT SELECT, INSERT, UPDATE ON notify.notifications TO notify_svc;
