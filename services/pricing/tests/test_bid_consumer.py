import json
from decimal import Decimal
from types import SimpleNamespace

from app.adapters.bid_consumer import BidEventsConsumer, decode
from tests.support import AUCTION


def event(**overrides) -> bytes:
    body = {
        "event_id": "00000000-0000-4000-8000-0000000000e1",
        "schema_version": 1,
        "auction_id": str(AUCTION),
        "bid_id": "00000000-0000-4000-8000-0000000000b1",
        "bidder_id": "00000000-0000-4000-8000-000000000001",
        "amount": "125.00",
        "server_seq": 7,
        "accepted_at": "2026-10-01T12:00:00.000Z",
        "idempotency_key": "key-00000001",
    }
    body.update(overrides)
    return json.dumps(body).encode()


def test_decode_reads_what_pricing_needs():
    bid = decode(event())
    assert (bid.auction_id, bid.server_seq, bid.amount) == (str(AUCTION), 7, Decimal("125.00"))
    assert bid.accepted_at.tzinfo is not None


def test_unknown_versions_and_garbage_are_skipped():
    assert decode(event(schema_version=2)) is None
    assert decode(event(amount=125.0)) is None
    assert decode(b"not json") is None
    assert decode(b"[1, 2]") is None
    assert decode(b"\xff\xfe") is None


class FakeKafka:
    def __init__(self, values):
        self.values = values
        self.commits = 0
        self.started = self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def commit(self):
        self.commits += 1

    def __aiter__(self):
        async def gen():
            for value in self.values:
                yield SimpleNamespace(value=value)
        return gen()


async def test_run_handles_every_message_and_commits_after_each():
    seen = []

    async def handler(bid):
        if bid.server_seq == 2:
            raise RuntimeError("boom")
        seen.append(bid.server_seq)

    kafka = FakeKafka([event(server_seq=1), b"junk", event(server_seq=2), event(server_seq=3)])
    await BidEventsConsumer(kafka, handler).run()
    assert seen == [1, 3]
    assert kafka.commits == 4  # skipped and failed events are not retried forever
    assert kafka.started and kafka.stopped
