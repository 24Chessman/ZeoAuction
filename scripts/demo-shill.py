"""Stage a shill-bidding ring on the running Compose stack (Plan 5 demo, segment 4).

Two seeded ring accounts (infra/postgres/seed/demo-mid-sem.sql) bid each other up on the seeded
compass listing through the real bid API, from one shared device fingerprint, a few seconds
apart. That is seller-linked, fast, same-device bidding, which ``shill-v1`` scores 1.0. The
fraud detector should raise a ``ShillAlert`` within the first few bids, long before the close.
The script then reads the detector's ``fraud_alerts_total`` metric to show it.

    .venv/Scripts/python.exe scripts/demo-shill.py               # 6 bids, 5 s apart
    .venv/Scripts/python.exe scripts/demo-shill.py --bids 10 --gap 3

Needs the stack up with both seeds applied, and the auth service accepting the seed password
(``AUTH_ACCEPT_SEED_PASSWORD``, on in docker-compose.yml). Test data only.
"""

import argparse
import re
import sys
import time
import uuid

import httpx

AUTH = "http://localhost:8001/api/v1"
BID = "http://localhost:8004/api/v1"
FRAUD_METRICS = "http://localhost:8011/metrics"
AUCTION = "00000000-0000-4000-8000-000000000203"
RING = ("ring1@zeo.local", "ring2@zeo.local")
PASSWORD = "zeo-dev-password"  # noqa: S105 - the public dev seed password
DEVICE = "fp_demo_ring_shared_laptop"
STARTING_PRICE = "2000.00"
INSPECT = (
    "Inspect: docker compose exec -T postgres psql -U postgres -d zeoauction -c \"SELECT score, "
    "signals, raised_before_close FROM fraud.fraud_alerts WHERE auction_id = "
    "'00000000-0000-4000-8000-000000000203'\""
)


def login(client: httpx.Client, email: str) -> str:
    response = client.post(f"{AUTH}/auth/login", json={"email": email, "password": PASSWORD})
    response.raise_for_status()
    return response.json()["access_token"]


def alerts_published(client: httpx.Client) -> float:
    text = client.get(FRAUD_METRICS).text
    match = re.search(r'fraud_alerts_total\{outcome="published"\} ([0-9.]+)', text)
    return float(match.group(1)) if match else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bids", type=int, default=6)
    parser.add_argument("--gap", type=float, default=5.0, help="seconds between bids")
    args = parser.parse_args(argv)

    with httpx.Client(timeout=10) as client:
        tokens = [login(client, email) for email in RING]
        before = alerts_published(client)
        amount = STARTING_PRICE
        for turn in range(args.bids):
            bidder = turn % len(RING)
            response = client.post(
                f"{BID}/auctions/{AUCTION}/bids",
                json={"amount": amount, "device_fingerprint": DEVICE},
                headers={"Authorization": f"Bearer {tokens[bidder]}",
                         "Idempotency-Key": f"demo-shill-{uuid.uuid4()}"},
            )
            body = response.json()
            if response.status_code >= 400:
                print(f"{RING[bidder]} refused: {body.get('code')} {body.get('message')}")
                amount = (body.get("details") or {}).get("min_next_bid", amount)
                continue
            print(f"{RING[bidder]:<16} bid {amount:>9}  seq {body['server_seq']:>3}  "
                  f"next minimum {body['min_next_bid']}")
            amount = body["min_next_bid"]
            time.sleep(args.gap)
        time.sleep(2)  # let the detector catch up with the last bid
        raised = alerts_published(client) - before
    print(f"\nShill alerts published while the ring bid: {raised:g}")
    print(INSPECT)
    return 0 if raised else 1


if __name__ == "__main__":
    sys.exit(main())
