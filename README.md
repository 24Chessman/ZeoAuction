# ZeoAuction

**Distributed Real-Time Auction Platform** — a microservices-based auction system built on Service-Oriented Architecture (SOA) principles, developed as a Web Services & SOA group project (M.Sc. IT, Semester 3).

Users create, bid on, and settle auctions across independently deployable services communicating through **Apache Kafka** (event-driven, asynchronous) and **REST APIs** (synchronous, request–response). Sellers must complete KYC verification before listing; the platform charges a flat convenience fee per sale; and settlement funds are held in **escrow** during a bounded buyer-protection window before release.

## Key Capabilities

- **High-throughput bidding** — authoritative server-side sequencing for deterministic conflict resolution on concurrent bids, with Redis-backed write buffering and batched persistence
- **Real-time updates** — WebSocket push (no polling) for live price changes and outbid alerts
- **In-flight fraud detection** — a streaming detector consumes the same Kafka topic as the bid pipeline to catch shill-bidding patterns before auction close, not in overnight batch jobs
- **Escrow-based settlement** — platform-held funds, released only on buyer confirmation, window expiry, or admin dispute adjudication
- **KYC-gated listing** — sellers must be verified before the listing endpoint accepts a request
- **Fault isolation** — circuit breakers, per-service health checks, and automatic restart so one failing subsystem doesn't take the platform down
- **Independent scaling** — each service scales horizontally on its own

## Architecture

Hybrid web application:
- **Frontend:** React 18 + Tailwind CSS (SPA), deployed to Vercel
- **Backend:** Python 3.11 + FastAPI microservices, containerized with Docker, deployed independently on Render
- **Messaging:** Apache Kafka (ordered, replayable event log feeding both bidding and fraud detection)
- **Database:** PostgreSQL 15 (ACID guarantees for money, escrow ledger, bid history)
- **Cache/Buffer:** Redis 7 (current-price reads, write buffering)
- **Real-time:** Native FastAPI WebSockets
- **Auth:** JWT (access + refresh), verification status carried as a claim
- **Document storage:** S3-compatible object storage, encrypted at rest, signed-URL access only
- **Payments:** Stripe (test mode) — functional simulation, no real funds handled
- **Observability:** Prometheus, Grafana, Jaeger
- **CI/CD:** GitHub Actions → Render (backend) / Vercel (frontend)

## Core Services / Components

| Component | Description |
|---|---|
| Auth & User Service | Registration, JWT issuance, roles, profiles, sessions |
| KYC & Seller Verification | Document submission, encrypted store, verification state machine, listing gate |
| Bid Processing | Validation, deterministic conflict resolution, idempotency keys, Redis buffering |
| Auction Orchestration | Lifecycle state machine, anti-snipe auto-extension, settlement transitions |
| Pricing Engine | Bid-velocity tracking, dynamic increment calculation, hot-auction flagging |
| Payment, Fees & Escrow | Stripe integration, convenience-fee engine, escrow hold/release, Saga compensation |
| Dispute Management | Dispute lifecycle, evidence capture, window enforcement, auto-release scheduler, adjudication |
| Fraud Detection | Shill-bid detection, device fingerprinting, bid-ring clustering on live event stream |
| WebSocket Gateway | Connection management, room fan-out, outbid alerts, reconnect handling |
| Admin & Moderation | Listing review, user suspension, audit log |
| Search & Analytics | Full-text search, filtering, seller dashboard, trend reporting |
| Frontend | Bidding UI, fee disclosure, KYC upload, dispute form, notifications |

## Settlement Policy (summary)

- **Convenience fee:** flat amount per completed sale (not a percentage), disclosed pre-bid, added at invoicing, non-refundable on buyer-fault disputes
- **Escrow hold:** captured total held by the platform until an explicit release transition — no code path pays a seller directly on capture
- **Protection window:** configurable (default 7 days) from ship date; disputes only accepted while open
- **Release triggers:** buyer confirmation, window expiry (auto-release), or dispute resolved in seller's favor
- **Refund trigger:** dispute resolved in buyer's favor, reversing the Stripe capture
- Full rules are documented in Section 5 of the project proposal and enforced by a time-accelerated test fixture covering every terminal state.

## Success Metrics (targets)

- **Throughput:** 1000 bids/sec aggregate across 50 concurrent auctions (≤0.1% error rate); 200 bids/sec against a single contended auction
- **Latency:** p95 bid acknowledgement < 500 ms; p95 WebSocket fan-out < 100 ms at 500 concurrent watchers
- **Settlement correctness:** 100% reconciliation across 1000 simulated settlements (zero tolerance)
- **KYC enforcement:** zero auctions created by unverified accounts
- **Fraud detection:** recall ≥ 0.90 at precision ≥ 0.75 on a seeded 500-auction dataset, alerts raised pre-close
- **Resilience:** any single backend service can be stopped without taking down the rest of the platform
- **Code quality:** 80% unit-test coverage, zero linting errors in CI, two approvals per PR

## Getting Started

> Setup instructions (Docker Compose, environment variables, service ports) will be added here as the infrastructure lands in Weeks 1–2.

```bash
# Clone the repo
git clone https://github.com/<org>/zeoauction.git
cd zeoauction

# Bring up the full stack locally
docker compose up --build
```

## Tech Stack

`Python 3.11` · `FastAPI` · `React 18` · `Tailwind CSS` · `Apache Kafka` · `PostgreSQL 15` · `Redis 7` · `Docker` · `Docker Compose` · `Render` · `Vercel` · `Stripe` · `Prometheus` · `Grafana` · `Jaeger` · `GitHub Actions`

## Team

Eight-member team, each allocated 200 hours (1600 total) against named component ownership. See the project proposal (`docs/ZeoAuctionProposal.pdf`) for the full role breakdown, timeline, and risk register.

## License

TBD — academic project (M.Sc. IT, Semester 3, Web Services & SOA).
