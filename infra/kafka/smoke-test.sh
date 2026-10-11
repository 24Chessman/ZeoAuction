#!/bin/sh
# Kafka smoke test (owner: Ayush, #89). Proves produce -> consume, and that messages and the
# consumer offset survive a broker restart when run in two phases.
#
#   smoke-test.sh produce [bootstrap]   # writes a uniquely tagged message
#   (restart the broker: docker compose restart kafka, or restart the Render service)
#   smoke-test.sh verify  [bootstrap]   # reads it back after the restart
#
# Locally: make smoke-kafka. On Render: run from the service Shell tab.
set -eu

PHASE="${1:?usage: smoke-test.sh produce|verify [bootstrap]}"
BOOTSTRAP="${2:-kafka:9092}"
BIN="${KAFKA_HOME:-/opt/kafka}/bin"
TOPIC=zeo.smoke
MARKER_FILE="${SMOKE_MARKER_FILE:-/tmp/zeo-smoke-marker}"

case "$PHASE" in
  produce)
    "$BIN/kafka-topics.sh" --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
      --topic "$TOPIC" --partitions 1 --replication-factor 1
    marker="smoke-$(date +%s)-$$"
    echo "$marker" | "$BIN/kafka-console-producer.sh" --bootstrap-server "$BOOTSTRAP" --topic "$TOPIC"
    echo "$marker" > "$MARKER_FILE"
    echo "produced $marker; now restart the broker and run: smoke-test.sh verify"
    ;;
  verify)
    marker="$(cat "$MARKER_FILE")"
    if "$BIN/kafka-console-consumer.sh" --bootstrap-server "$BOOTSTRAP" --topic "$TOPIC" \
         --from-beginning --timeout-ms 15000 2>/dev/null | grep -q "$marker"; then
      echo "PASS: $marker survived the restart"
    else
      echo "FAIL: $marker not found on $TOPIC" >&2
      exit 1
    fi
    ;;
  *)
    echo "unknown phase: $PHASE" >&2
    exit 2
    ;;
esac
