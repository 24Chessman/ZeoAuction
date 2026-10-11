"""Per-connection send buffer with price coalescing (#94, SDD 7.8.1).

Fan-out never writes to a socket; it puts messages into each connection's :class:`Outbox`
without waiting, and one writer task per connection drains it. A slow watcher therefore only
fills its own outbox, and never slows the consumer or other watchers.

* ``price_update`` is a last-write-wins value: while one is still waiting for an auction, a
  newer one replaces it (the old one is dropped and the new one goes to the back, so it is
  never delivered before a message that preceded it). Coalescing is lossless in effect.
* Everything else (``outbid``, ``auction_extended``, ``auction_closed``, ``notification``) is
  **never** coalesced or dropped. If those alone exceed ``limit``, the client cannot keep up:
  :class:`OutboxOverflow` tells the connection to close, and the client reconnects and
  resubscribes with its last ``server_seq`` to get a fresh snapshot.
"""

import asyncio
from collections import deque
from typing import Any

COALESCED_TYPE = "price_update"


class OutboxOverflow(Exception):
    pass


class OutboxClosed(Exception):
    pass


class _Entry:
    __slots__ = ("message", "alive")

    def __init__(self, message: dict[str, Any]) -> None:
        self.message = message
        self.alive = True


class Outbox:
    def __init__(self, limit: int = 256) -> None:
        self.limit = limit
        self._queue: deque[_Entry] = deque()
        self._pending_price: dict[str, _Entry] = {}
        self._size = 0
        self._ready = asyncio.Event()
        self.coalesced = 0
        self.closed = False

    def __len__(self) -> int:
        return self._size

    def put(self, message: dict[str, Any]) -> bool:
        """Queue ``message`` without waiting. Returns True if it replaced an older price."""
        if self.closed:
            return False
        replaced = False
        if message.get("type") == COALESCED_TYPE:
            older = self._pending_price.get(message["auction_id"])
            if older is not None:
                older.alive = False
                self._size -= 1
                self.coalesced += 1
                replaced = True
        elif self._size >= self.limit:
            raise OutboxOverflow(f"{self._size} undelivered messages")
        entry = _Entry(message)
        self._queue.append(entry)
        self._size += 1
        if message.get("type") == COALESCED_TYPE:
            self._pending_price[message["auction_id"]] = entry
        self._ready.set()
        return replaced

    async def get(self) -> dict[str, Any]:
        """The next live message, waiting for one if necessary."""
        while True:
            while self._queue:
                entry = self._queue.popleft()
                if not entry.alive:
                    continue
                self._size -= 1
                message = entry.message
                if message.get("type") == COALESCED_TYPE and \
                        self._pending_price.get(message["auction_id"]) is entry:
                    del self._pending_price[message["auction_id"]]
                return message
            if self.closed:
                raise OutboxClosed
            self._ready.clear()
            await self._ready.wait()

    def close(self) -> None:
        self.closed = True
        self._ready.set()
