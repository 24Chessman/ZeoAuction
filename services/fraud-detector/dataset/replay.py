"""Replay the labelled dataset into ``bid.events`` (#51).

The fixture is already a stream of ``BidAccepted v1`` events, so it can be published exactly as
the bid service would publish live traffic: keyed by ``auction_id``, each auction's bids in
``server_seq`` order. The fraud detector then consumes it like production (Plan 5, #52-#57).

    python -m dataset.replay --bootstrap localhost:29092 \\
        --file ../../tests/fixtures/fraud/dataset-v1.jsonl.gz --shift-to-now

``--shift-to-now`` moves every timestamp by one offset so the latest close lands in the future,
which keeps the "alert before close" rule (AC-14) meaningful during a live demo.
"""

import argparse
import asyncio
import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

BID_EVENTS_TOPIC = "bid.events"


class Producer(Protocol):
    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> Any: ...


def read_events(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            if line.strip():
                yield json.loads(line)


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _format(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def shift_to(events: list[dict[str, Any]], latest_close: datetime) -> list[dict[str, Any]]:
    """Shift every timestamp by the same offset so the latest close equals ``latest_close``."""
    if not events:
        return events
    newest = max(_parse(e.get("auction_closes_at", e["accepted_at"])) for e in events)
    offset = latest_close - newest
    shifted = []
    for event in events:
        moved = dict(event)
        moved["accepted_at"] = _format(_parse(event["accepted_at"]) + offset)
        if "auction_closes_at" in event:
            moved["auction_closes_at"] = _format(_parse(event["auction_closes_at"]) + offset)
        shifted.append(moved)
    return shifted


def in_publish_order(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Global time order, with each auction's bids strictly in ``server_seq`` order."""
    return sorted(events, key=lambda e: (e["accepted_at"], e["auction_id"], e["server_seq"]))


async def publish(
    events: list[dict[str, Any]],
    producer: Producer,
    *,
    topic: str = BID_EVENTS_TOPIC,
    rate_per_second: float = 0.0,
) -> int:
    """Publish every event, waiting for each broker acknowledgement. Returns the count."""
    delay = 1.0 / rate_per_second if rate_per_second > 0 else 0.0
    count = 0
    for event in in_publish_order(events):
        value = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        await producer.send_and_wait(topic, value=value, key=event["auction_id"].encode())
        count += 1
        if delay:
            await asyncio.sleep(delay)
    return count


async def _main(argv: list[str] | None = None) -> None:  # pragma: no cover - needs a broker
    from aiokafka import AIOKafkaProducer

    parser = argparse.ArgumentParser(description="Replay the fraud dataset into bid.events")
    parser.add_argument("--bootstrap", default="localhost:29092")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--rate", type=float, default=0.0, help="events per second; 0 = no limit")
    parser.add_argument("--shift-to-now", action="store_true")
    args = parser.parse_args(argv)

    events = list(read_events(args.file))
    if args.shift_to_now:
        events = shift_to(events, datetime.now(UTC) + timedelta(hours=1))
    producer = AIOKafkaProducer(bootstrap_servers=args.bootstrap, acks="all",
                                enable_idempotence=True, client_id="fraud-dataset-replay")
    await producer.start()
    try:
        sent = await publish(events, producer, rate_per_second=args.rate)
    finally:
        await producer.stop()
    print(f"published {sent} events to {BID_EVENTS_TOPIC}")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
