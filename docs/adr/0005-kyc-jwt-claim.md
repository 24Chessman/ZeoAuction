# ADR-0005: KYC status carried as a JWT claim with forced refresh

| | |
|---|---|
| **Status** | **Accepted** (SDD §2.6.5, ratified in Plan 7, #49) |
| **Date** | 2026-11-02 |
| **Owner** | Sagar / Ayush |
| **Deciders** | Sagar, Ayush, Sumit |
| **Requirements** | FR-KYC-1, AC-06; SDD §2.6.5; contracts/openapi/internal/kyc-status.v1.yaml (CT-2) |

## Context

Auctions must strictly enforce the seller verification gate (AC-06: direct API calls with
unverified tokens must create zero listings). However, querying the KYC database or making an
internal RPC call to the KYC service on every auction creation or bid validation adds inter-service
latency and creates a tight runtime coupling.

## Options considered

1. **Synchronous RPC call to KYC service on every listing**: reliable freshness, but adds 20-50 ms network latency per request and makes auction creation fragile to KYC service restarts.
2. **Read-through Redis cache**: faster, but requires another network round-trip and complex cache invalidation.
3. **Stateless JWT claims (`kyc_status`, `tv`) with Redis forced refresh**: JWT carries `kyc_status`, `suspended`, and `tv` (token version). The gate validates claims locally in memory. When KYC status changes, Redis `tv:{user_id}` is bumped to force immediate token refresh.

## Decision

**Option 3: Signed JWT claims with forced token refresh.**
1. The Auth service issues JWT access tokens carrying:
   - `kyc_status`: `NOT_SUBMITTED`, `SUBMITTED`, `UNDER_REVIEW`, `VERIFIED`, `REJECTED`, `SUSPENDED`
   - `suspended`: `bool`
   - `tv`: integer token version
2. Listing gates (`zeo_common.gateway.VerifiedSeller`) evaluate the JWT claims in memory:
   - Verifies signature and expiration
   - Checks `token_version >= Redis tv:{user_id}` (if older, returns `401 UNAUTHENTICATED` with `details.reason = TOKEN_STALE`)
   - Rejects suspended users with `403 ACCOUNT_SUSPENDED`
   - Rejects non-verified users with `403 SELLER_NOT_VERIFIED`
3. When KYC verifies or suspends an account, it updates `auth.users.token_version` and publishes `tv:{user_id}` to Redis in the same transaction.

## Consequences

- **Performance**: Zero database or RPC overhead on the listing creation hot path.
- **Freshness**: Upgraded sellers or suspended users have their privileges updated immediately upon next request via forced token refresh (within milliseconds, instead of waiting for token expiration).
- **Security**: Hard gate satisfies AC-06 completely.

## Evidence

- Verified by contract suite `tests/contracts/test_kyc_pricing_ct2_ct3.py`.
- Unit tests in `libs/zeo-common/tests/test_gateway.py` validating stale token rejection and verification gating.
