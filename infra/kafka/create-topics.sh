#!/bin/sh
# Creates the four ZeoAuction topics (owner: Ayush; topology: Sumit, #29).
# Source of truth: contracts/events/topics.yaml. tests/contracts/test_topics.py fails CI
# if this script and that file disagree.
# Maximum 2 partitions per topic for production configuration.
#
# Usage: create-topics.sh [bootstrap-server]   (default kafka:9092)
set -eu

BOOTSTRAP="${1:-kafka:9092}"
TOPICS_BIN="${KAFKA_HOME:-/opt/kafka}/bin/kafka-topics.sh"
DAY_MS=86400000

create() {
  topic="$1"; partitions="$2"; shift 2
  "$TOPICS_BIN" --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
    --topic "$topic" --partitions "$partitions" --replication-factor 1 "$@"
  echo "topic ready: $topic ($partitions partitions)"
}

# bid.events: highest volume, keyed by auction_id so one auction is one ordered partition (max 2).
create bid.events      2 --config retention.ms=$((7 * DAY_MS))
# auction.events: lifecycle transitions; low volume, per-auction ordering matters (max 2).
create auction.events  2 --config retention.ms=$((7 * DAY_MS))
# payment.events: settlement audit trail, keyed by order_id; compaction keeps the latest per order (max 2).
create payment.events  2 --config retention.ms=$((30 * DAY_MS)) --config cleanup.policy=compact,delete
# fraud.alerts: low volume, kept long enough to correlate with adjudicated disputes (max 2).
create fraud.alerts    2 --config retention.ms=$((30 * DAY_MS))

"$TOPICS_BIN" --bootstrap-server "$BOOTSTRAP" --list
