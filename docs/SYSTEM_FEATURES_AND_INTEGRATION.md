# ZeoAuction — Feature Set, Full-Stack & API Integration Guide

This document provides a comprehensive breakdown of the **ZeoAuction** platform, covering the complete functional feature set, the end-to-end integration between Frontend, Backend, and Database tiers, and synchronous vs. asynchronous API integration architectures.

---

## 1. Complete Feature Set (Fully Functional App)

ZeoAuction is designed with a **Trust and Safety First** philosophy, serving three primary user roles: **Buyers/Bidders**, **Sellers**, and **Administrators**.

```mermaid
flowchart TD
    Root["ZeoAuction Core System"]

    subgraph Buyers["Buyer Experience"]
        B1["Identity and Gmail OTP Verification"]
        B2["Live WebSocket Bidding Room"]
        B3["Anti-Snipe Countdown and Alerts"]
        B4["Razorpay Checkout and Escrow"]
    end

    subgraph Sellers["Seller Experience"]
        S1["Aadhaar QR Offline RSA Verification"]
        S2["KYC Listing Gate Enforcement"]
        S3["Multi-Photo S3 Listing Upload"]
        S4["Order Tracking and Escrow Payout"]
    end

    subgraph Admins["Admin and Moderation"]
        A1["KYC Submission Review Queue"]
        A2["Real-Time Fraud Alerts and Bans"]
        A3["Append-Only Escrow Ledger"]
        A4["Dispute Adjudication"]
    end

    subgraph Engine["Autonomous Services"]
        E1["Redis Sub-Millisecond Bid Lock"]
        E2["Kafka Sequential Event Streaming"]
        E3["Bid-Flusher Batch Database Sync"]
        E4["Escrow-Sweep Scheduled Worker"]
    end

    Root --> Buyers
    Root --> Sellers
    Root --> Admins
    Root --> Engine
```

### A. Authentication, User Management & Verification
- **Email Verification & Registration**: New users register with an email, password, and display name. Registration requires email verification via a 6-digit Gmail OTP or verification link before first login.
- **Stateless JWT Sessions**: 15-minute access tokens carry identity (`sub`), user role (`buyer`, `seller`, `admin`), KYC verification status (`kyc_status`), and account status (`suspended`).
- **Secure Refresh Token Rotation**: Refresh tokens are stored strictly as SHA-256 hashes (`hash_refresh_token`). A single refresh token rotation invalidates previous tokens and issues a new pair.
- **Role & KYC Gating Middleware**: FastAPI dependency (`zeo_common.auth`) intercepts incoming requests and rejects unauthorized calls with uniform error envelopes.

### B. Seller Onboarding & KYC Verification Gate
- **Pre-Listing KYC Gate**: Sellers cannot draft or publish auctions without passing KYC verification (`kyc_status: approved`).
- **Aadhaar Secure QR Code Upload**: Sellers upload a photograph or scan of their UIDAI Secure QR code.
- **Offline Cryptographic Verification**: The `kyc` service parses the QR payload, extracts UIDAI XML demographic data, and verifies the 2048-bit RSA digital signature against UIDAI's offline public certificate (`SHA256withRSA`).
- **Document Management**: Verification documents and photos are stored in private Supabase S3 buckets with time-limited presigned URLs.

### C. Catalog, Listing & Lifecycle Orchestration
- **Listing Creation**: Verified sellers create listings specifying title, category, starting price, reserve price, increment rules, and scheduled duration.
- **Multi-Photo Management**: Sellers upload up to 6 photos (JPEG/PNG/WebP) directly streamed to S3-compatible storage.
- **Strict State Machine**: Auctions transition predictably:
  $$\text{DRAFT} \longrightarrow \text{SCHEDULED} \longrightarrow \text{OPEN} \longrightarrow \text{CLOSING} \longrightarrow \text{CLOSED} \longrightarrow \text{SETTLED / CANCELLED}$$
- **Anti-Snipe Extensions**: Bids placed in the final minutes automatically extend the auction clock to ensure fair closing.

### D. Real-Time High-Throughput Bidding
- **Sub-Millisecond Bid Ingestion**: Bids are validated against the current high bid and reserve rules using Upstash Redis.
- **Idempotency Protection**: Every bid submission requires an `Idempotency-Key` header; retries return the original accepted bid without duplicating entries.
- **Dynamic Increment Pricing**: The `pricing` service calculates dynamic minimum bid increments based on current bid brackets.
- **WebSocket Gateway (`ws-gateway`)**: Broadcasts real-time bid updates, countdown clocks, and outbid events to connected browser rooms.
- **Asynchronous Batch Flushing (`bid-flusher`)**: High-velocity in-memory bids are buffered in Redis/Kafka and flushed periodically to PostgreSQL in batches of 500 to protect the database from connection exhaustion.

### E. Post-Auction Settlement, Razorpay & Escrow
- **Automatic Order Generation**: When an auction closes, the system generates an order and invoices the winning bidder.
- **Razorpay Checkout Integration**: Winners pay via Razorpay Checkout in test mode.
- **Webhook Authorization**: Payments are authorized and captured via cryptographic webhook signatures (`RAZORPAY_WEBHOOK_SECRET`).
- **Double-Entry Escrow Ledger**: Captured funds are deposited into an append-only simulated escrow ledger (`payment.escrow_ledger`).
- **Buyer Protection Window & Sweep**: Funds remain locked in escrow for a designated protection period. If no dispute is lodged, the `escrow-sweep` cron worker automatically settles and releases seller payout.

### F. Dispute Resolution & Platform Trust
- **Dispute Filing**: Buyers can open a dispute before the protection window closes, providing reasons and image evidence.
- **In-Flight Fraud Detection**: The `fraud-detector` worker consumes the Kafka `bid.events` stream in real time, detecting suspicious shill bidding or velocity spikes.
- **Admin Moderation Portal**: Administrators review pending KYC submissions, monitor fraud alerts, inspect immutable audit logs, and adjudicate disputes.

---

## 2. Frontend + Backend + Database Integration

```mermaid
sequenceDiagram
    autonumber
    actor User as User Browser
    participant SPA as React Frontend (Vite)
    participant GW as API Gateway (Nginx)
    participant Auth as auth-user Service
    participant Bid as bid Service
    participant Redis as Upstash Redis
    participant DB as NeonDB (PostgreSQL)
    participant Kafka as Aiven Kafka

    %% Authentication Flow
    Note over User, DB: 1. User Authentication Flow
    User->>SPA: Enter email & password
    SPA->>GW: POST /api/v1/auth/login
    GW->>Auth: Forward to auth-user (8001)
    Auth->>DB: Query auth.users (verify hash & KYC claim)
    DB-->>Auth: User record
    Auth-->>GW: Issue Access JWT (15-min) + Refresh Token
    GW-->>SPA: Store access token in memory, refresh token in cookie/session

    %% Real-time Bidding Flow
    Note over User, Kafka: 2. Real-Time Bidding Flow
    User->>SPA: Click "Place Bid" (120.00)
    SPA->>GW: POST /api/v1/auctions/{id}/bids (with JWT and Idempotency-Key)
    GW->>Bid: Forward to bid service (8004)
    Bid->>Redis: Check Idempotency and validate minimum increment
    Bid->>Redis: Atomic conditional update of price:{auction_id}
    Bid-->>GW: Return 201 Created (BidAccepted)
    GW-->>SPA: Display "Bid Accepted"
    Bid-)Kafka: Publish BidPlacedEvent to bid.events topic
    Kafka-)GW: WS Gateway consumes event
    GW-)SPA: Broadcast real-time bid over WebSocket (/ws)
```

### Full-Stack Architecture Tiers

| Tier | Component | Responsibilities & Integration Details |
| :--- | :--- | :--- |
| **Frontend Tier** | **React 18 SPA (TypeScript)** | • Clean component hierarchy with Tailwind CSS.<br/>• Dedicated API layer (`src/lib/api/index.ts`) abstracting network calls.<br/>• Centralized session manager with automatic JWT refresh on `401 UNAUTHENTICATED`.<br/>• Real-time WebSocket manager (`LiveClient`) with automatic reconnect and exponential backoff.<br/>• Configurable via `ZEO_API_GATEWAY_URL` and `ZEO_WS_URL`. |
| **Gateway Tier** | **Nginx Reverse Proxy** | • Listens on port 80/443; terminates public traffic.<br/>• Translates path routes (`/api/v1/...`) to internal backend service containers.<br/>• Upgrades HTTP connections to WebSocket protocols for `/ws`.<br/>• Standardizes proxy headers (`Host`, `X-Real-IP`, `X-Forwarded-For`). |
| **Backend Tier** | **13 FastAPI Microservices** | • Built on top of `libs/zeo-common`.<br/>• Standardized error envelopes (`code`, `message`, `details`, `request_id`).<br/>• Standardized health checks (`/healthz`, `/readyz`, `/metrics`).<br/>• Asynchronous I/O via Python `asyncio` and `httpx`. |
| **Database Tier** | **NeonDB PostgreSQL** | • **Schema Isolation**: Each service owns its schema (`auth`, `kyc`, `auction`, `bid`, `payment`, `dispute`, `search`, `admin`, `notify`, `fraud`).<br/>• **No Cross-Schema Foreign Keys**: Loose coupling using standard UUIDs.<br/>• **Append-Only Guarantees**: Database triggers prevent `UPDATE` and `DELETE` operations on audit and ledger tables.<br/>• **Enforced Encryption**: Connections require `sslmode=require`. |
| **Cache Tier** | **Upstash Redis** | • Ephemeral, high-velocity data store.<br/>• Manages bid locking, idempotency keys (`idem:{key}`), and active room connections.<br/>• Connected via TLS (`rediss://`). |
| **Event Tier** | **Aiven Kafka** | • Asynchronous backbone for service decoupling.<br/>• Partitioned strictly by `auction_id` for deterministic sequential processing.<br/>• Authenticated via `SASL_SSL` and `SCRAM-SHA-256`. |

---

## 3. API Integration (On-Need Basis)

ZeoAuction enforces a strict distinction between **synchronous REST** calls and **asynchronous event-driven** calls. Synchronous HTTP is used only when the caller cannot proceed without an immediate answer. All other side effects are handled asynchronously through Kafka.

```mermaid
flowchart TD
    subgraph SynchronousRest["Synchronous REST APIs (Circuit-Broken)"]
        CT1["CT-1: Bid -> Auction Orchestrator (GET /auctions/{id}/state)"]
        CT2["CT-2: Auction -> KYC Gate (Reads JWT kyc_status claim directly)"]
        CT3["CT-3: Bid -> Pricing (GET /pricing/{id}/min-increment)"]
        CT4["CT-4: Auction -> Payment (POST /internal/orders)"]
    end

    subgraph AsynchronousKafka["Asynchronous Event Streaming (Kafka)"]
        BidEvents["bid.events"]
        AuctionEvents["auction.events"]
        PaymentEvents["payment.events"]
    end

    subgraph ThirdPartyAPIs["External 3rd-Party APIs"]
        RazorpayAPI["Razorpay Payment Gateway (Order creation and webhook capture)"]
        GmailSMTP["Gmail SMTP / Google OAuth (Transactional OTP delivery)"]
        SupabaseS3API["Supabase S3 Storage (Presigned URL photo upload)"]
        UidaiCert["UIDAI Offline Certificate (2048-bit RSA signature verify)"]
    end
```

### A. Synchronous Contract Boundaries (REST)

The four synchronous boundaries are governed by consumer contract tests (`tests/contracts`) and protected by circuit breakers:

| Contract ID | Caller $\to$ Target | Endpoint | Fallback Policy on Failure |
| :--- | :--- | :--- | :--- |
| **CT-1** | `bid` $\to$ `auction-orchestrator` | `GET /api/v1/auctions/{id}/state` | Circuit breaker trips after 5 failures in 10s. Serves cached state if $< 2\text{s}$ old; otherwise raises `AUCTION_STATE_UNAVAILABLE`. |
| **CT-2** | `auction-orchestrator` $\to$ `kyc` | *Zero Network Call* | Zero network call on the critical path. The listing gate validates the seller's `kyc_status` claim directly from the cryptographically signed JWT. |
| **CT-3** | `bid` $\to$ `pricing` | `GET /api/v1/pricing/{id}/min-increment` | Falls back to last cached increment; marks bid as `increment_stale`. |
| **CT-4** | `auction-orchestrator` $\to$ `payment-escrow` | `POST /internal/orders` | Auction remains `CLOSED`; background timer retries order creation with the same `Idempotency-Key`. |

### B. Asynchronous Event-Driven APIs (Kafka)

All cross-service data projections and reactive actions occur asynchronously over Kafka topics:

| Topic Name | Key | Event Types | Consumers & Actions |
| :--- | :--- | :--- | :--- |
| `bid.events` | `auction_id` | `BidPlaced`, `BidOutbid` | • **pricing**: Recalculates dynamic bracket increments.<br/>• **bid-flusher**: Buffers and persists accepted bids to database.<br/>• **fraud-detector**: Evaluates real-time bid velocity and shill scoring.<br/>• **ws-gateway**: Pushes real-time updates to connected browsers. |
| `auction.events` | `auction_id` | `AuctionOpened`, `AuctionClosing`, `AuctionClosed` | • **search-analytics**: Updates full-text search index.<br/>• **ws-gateway**: Emits lifecycle status changes to room participants. |
| `payment.events` | `order_id` | `PaymentCaptured`, `EscrowReleased`, `DisputeOpened` | • **auction-orchestrator**: Marks auction as `SETTLED`.<br/>• **escrow-sweep**: Cancels automatic sweep timer if dispute opened.<br/>• **ws-gateway**: Emits payment confirmation to buyer. |

### C. Third-Party External API Integrations

1. **Razorpay Payments**:
   - `orders.create`: Initiates payment session when winner proceeds to checkout.
   - Webhook verification: Validates `payment.authorized` events using HMAC-SHA256 signatures before capturing funds to escrow.
2. **Gmail SMTP Service**:
   - Sends transactional 6-digit OTP verification codes via TLS port 587 using Google App Passwords.
3. **Supabase S3 API**:
   - Generates presigned URLs for direct multi-part photo uploads, reducing server CPU and memory overhead.
4. **UIDAI Public Certificate Registry**:
   - Offline verification of Aadhaar QR demographic data using UIDAI's trusted certificate root (`SHA256withRSA`).

---

## 4. Verification & Testing Strategy

The integrated platform is protected by a multi-tier testing suite:
- **Unit Tests**: Executed across all 13 services with an enforced 80% code coverage threshold.
- **Contract Tests (`tests/contracts`)**: Verifies that synchronous schema models and circuit breaker fallbacks strictly comply with API agreements.
- **End-to-End Suite (`tests/e2e`)**: Validates complete user journeys (seller KYC $\to$ listing creation $\to$ live bidding $\to$ auction close $\to$ payment capture $\to$ escrow sweep).
- **Frontend Vitest Suite (`npm run test`)**: 10 test suites covering mock services, money formatting, WebSocket live client reconnection, and form validation.
