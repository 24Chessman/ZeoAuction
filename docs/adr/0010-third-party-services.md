# ADR-0010: Push notifications and image hosting

| | |
|---|---|
| **Status** | **Proposed**: the team decides at the Plan 1 review (Aug 14) |
| **Date** | 2026-08-14 |
| **Owners** | Ayush (infrastructure), Gaurang (frontend) |
| **Requirements** | FR-UI-4, FR-WS-2, NFR-SEC-2; SDD 2.2, 8.9; proposal §7 |

## Context

Proposal §7 lists four third-party APIs: Razorpay, **Firebase Cloud Messaging**, **Cloudinary** and Prometheus.
The SDD takes a different position:

- Notifications travel over the platform's own WebSocket, and "no third-party push service is a dependency" (§8.9).
- Documents and evidence go to S3-compatible object storage behind signed URLs (§4.2.1, §9.1).

## Proposed decision

| Service | Decision | Scope |
|---|---|---|
| Firebase Cloud Messaging | **Optional, deferred.** In-session notifications use the WebSocket `notification` message plus `GET /api/v1/notifications`. FCM may be added in Plan 6 as an extra channel for users who aren't connected, and only if time allows. It is never on the critical path | Plan 6, optional |
| Cloudinary | **Listing images only**, if we adopt it. It is **never** used for KYC documents or dispute evidence, which stay in encrypted S3-compatible storage behind signed URLs | Plan 3 decision point |
| S3-compatible storage | SeaweedFS (S3 API) locally; the hosted provider is chosen in Plan 3 (#96) | Plan 1 (local), Plan 3 (hosted) |
| Prometheus | Adopted (with Grafana and Jaeger) | Plan 7 |

## Consequences

- The fan-out latency target (p95 < 100 ms) only depends on our own gateway.
- KYC personal data never leaves the encrypted store we control, as the retention ADR (Plan 7, #49) requires.
- If the course requires every API listed in the proposal to be used, FCM and Cloudinary each get a
  small, isolated integration, and they don't become dependencies of the demo path.
