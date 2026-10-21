"""Device-fingerprint signals (#54, FR-FRAUD-5; SDD Table 5.3 ``fingerprintOverlap``).

Every ``BidAccepted v1`` carries the ``device_fingerprint`` the bid was placed from (indexed
in ``bid.bids(device_fingerprint)``). Two views of the same index feed the scorer:

* :meth:`FingerprintIndex.sharers`: other accounts ever seen on any of this bidder's devices,
  across every auction. Households share a device too, so on its own this is weak.
* :meth:`FingerprintIndex.overlap_in_auction`: other accounts bidding **in the same auction**
  from a device this bidder used there. Two "different" people on one device pushing the same
  auction is what a ring looks like and a household rarely does; on the v1 dataset it nearly
  halves the false positives of the global count (``docs/fraud/v1-measurement.md``).

Both are also inputs to ring clustering (#55, Plan 6). A missing fingerprint is no evidence
either way and adds nothing.
"""

from collections import defaultdict


class FingerprintIndex:
    def __init__(self) -> None:
        self._bidders: dict[str, set[str]] = defaultdict(set)  # device -> accounts
        self._devices: dict[str, set[str]] = defaultdict(set)  # account -> devices
        # auction -> device -> accounts, and auction -> account -> devices
        self._auction_bidders: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set))
        self._auction_devices: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set))

    def observe(self, auction_id: str, bidder_id: str, fingerprint: str | None) -> None:
        if not fingerprint:
            return
        self._bidders[fingerprint].add(bidder_id)
        self._devices[bidder_id].add(fingerprint)
        self._auction_bidders[auction_id][fingerprint].add(bidder_id)
        self._auction_devices[auction_id][bidder_id].add(fingerprint)

    def sharers(self, bidder_id: str) -> int:
        devices = self._devices.get(bidder_id)
        if not devices:
            return 0
        others = set().union(*(self._bidders[d] for d in devices))
        return len(others - {bidder_id})

    def overlap_in_auction(self, auction_id: str, bidder_id: str) -> int:
        devices = self._auction_devices.get(auction_id, {}).get(bidder_id)
        if not devices:
            return 0
        by_device = self._auction_bidders[auction_id]
        others = set().union(*(by_device[d] for d in devices))
        return len(others - {bidder_id})

    def forget_auction(self, auction_id: str) -> None:
        """Drop a closed auction's view; the cross-auction index is kept for clustering."""
        self._auction_bidders.pop(auction_id, None)
        self._auction_devices.pop(auction_id, None)
