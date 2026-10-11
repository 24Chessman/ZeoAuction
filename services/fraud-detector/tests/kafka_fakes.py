"""An in-memory stand-in for a Kafka topic with consumer-group offsets.

``FakeBroker`` partitions by key exactly like the real topic is used (all of an auction's bids on
one partition, in publish order) and stores committed offsets per group, so a new consumer in
the same group resumes where the last one committed. ``FakeConsumer`` interleaves partitions the
way a real consumer does, which is what makes per-auction ordering worth testing.
"""

import zlib
from types import SimpleNamespace


class FakeBroker:
    def __init__(self, partitions: int = 12) -> None:
        self.partitions = partitions
        self.logs: dict[str, list[list[bytes]]] = {}
        self.committed: dict[tuple[str, str], dict[int, int]] = {}

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        log = self.logs.setdefault(topic, [[] for _ in range(self.partitions)])
        log[zlib.crc32(key) % self.partitions].append(value)

    def consumer(self, topic: str, group: str, *, limit: int | None = None,
                 fail_commit_at: int | None = None) -> "FakeConsumer":
        return FakeConsumer(self, topic, group, limit=limit, fail_commit_at=fail_commit_at)


class CommitFailed(Exception):
    """Stands in for the process dying between handling a message and committing it."""


class FakeConsumer:
    def __init__(self, broker: FakeBroker, topic: str, group: str, *, limit: int | None,
                 fail_commit_at: int | None) -> None:
        self.broker = broker
        self.topic = topic
        self.group = group
        self.limit = limit
        self.fail_commit_at = fail_commit_at
        self.positions: dict[int, int] = {}
        self.delivered = 0
        self.commits = 0
        self.started = self.stopped = False

    async def start(self) -> None:
        self.started = True
        self.positions = dict(self.broker.committed.get((self.topic, self.group), {}))

    async def stop(self) -> None:
        self.stopped = True

    async def commit(self) -> None:
        self.commits += 1
        if self.fail_commit_at is not None and self.commits == self.fail_commit_at:
            raise CommitFailed
        self.broker.committed[(self.topic, self.group)] = dict(self.positions)

    def __aiter__(self):
        async def messages():
            log = self.broker.logs.get(self.topic, [])
            while self.limit is None or self.delivered < self.limit:
                progressed = False
                for partition, entries in enumerate(log):  # round-robin across partitions
                    offset = self.positions.get(partition, 0)
                    if offset >= len(entries):
                        continue
                    if self.limit is not None and self.delivered >= self.limit:
                        return
                    self.positions[partition] = offset + 1
                    self.delivered += 1
                    progressed = True
                    yield SimpleNamespace(topic=self.topic, partition=partition, offset=offset,
                                          value=entries[offset])
                if not progressed:
                    return
        return messages()
