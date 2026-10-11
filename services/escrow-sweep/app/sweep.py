"""Escrow sweep (cron) — see services/escrow-sweep/README.md.

Render runs ``python -m app.sweep`` every minute as a Cron Job (ADR-0006); Compose runs it in a
60-second loop. Each run must be idempotent: overlapping runs are safe because every release
carries the key ``order:{id}:release``.
"""

import logging

from zeo_common.logging_setup import configure_logging

logger = logging.getLogger("escrow-sweep")


def run_once() -> int:
    """Release every expired protection window. Returns the number of orders released.

    Placeholder until Plan 6 (#25): the query over ``payment.orders`` (state = SHIPPED and
    ``protection_window_ends_at`` <= now) and the release call to Payment are not built yet.
    """
    logger.info("escrow sweep run: release logic lands in Plan 6 (#25); nothing released")
    return 0


def main() -> None:
    configure_logging("escrow-sweep")
    released = run_once()
    logger.info("escrow sweep finished: %d order(s) released", released)


if __name__ == "__main__":
    main()
