# Plan 5 — Fraud Detection v1 & Mid-Semester Demo

| | |
|---|---|
| **Weeks** | 10–11 |
| **Dates** | Mon Oct 5 – Fri Oct 16, 2026 |
| **Jira sprint** | sprint-5 |
| **Milestone** | #107 *Fraud Detection v1 integrated* (owner: Harshal), due **Fri Oct 9** |
| **Key event** | **Mid-Semester Demo — Mon Oct 12** (week 11) |
| **Proposal phase** | Week 10: Fraud Detection v1 — streaming shill detection scored against the week-3 dataset, dispute record creation, demo preparation. Week 11: Mid-Semester Demo |

## Goal

**Week 10:** streaming shill-bidding detection runs in flight on the live bid topic, scored against the
labelled dataset from Plan 2, and the whole system is **frozen and rehearsed** for the demo.

**Week 11:** give the mid-semester demo on Oct 12: *one end-to-end auction, from KYC-gated listing through bid to
settlement with the fee into escrow, plus a code walkthrough*. After the demo, make settlement robust with Saga
compensations and idempotent webhooks, and bring the pricing engine up to 80% coverage.

## Work breakdown (Jira)

| Jira | Task | Owner | Epic | Hours | Due |
|---|---|---|---|---|---|
| #53 | Implement shill-bidding detector | Harshal | Fraud Detection | 45 | Oct 9 |
| #54 | Implement device fingerprinting signals | Harshal | Fraud Detection | 25 | Oct 9 |
| #63 | Implement Saga coordination and compensation paths | Jaydip | Payment | 20 | Oct 16 |
| #64 | Handle payment-provider webhooks with idempotency guards | Jaydip | Payment | 10 | Oct 16 |
| #45 | Unit-test and tune the pricing engine to 80% coverage | Sagar | Pricing Engine | 10 | Oct 16 |
| #107 | **Milestone: Fraud Detection v1 integrated** | Harshal | Milestones | – | Oct 9 |

## What we will do

### Week 10 — Fraud Detection v1 (Harshal)
- **Shill detector (#53)**: score each event in the per-auction `SlidingWindow` using the SDD §5.4.2 signals:
  `bidVelocity`, `selfBidRatio`, `interArrivalStdDev`, `fingerprintOverlap`, `accountAgeDays`,
  `winRateWithSeller`, `graphDegreeToSeller`. Publish `ShillAlert v1` to `fraud.alerts`.
  `AlertPublisher.mustPrecedeClose` asserts the alert comes **before the auction closes**. A late alert counts as a miss.
- **Device fingerprinting (#54)**: fingerprint features taken from `device_fingerprint` on `BidAccepted`, backed by the
  `bids(device_fingerprint)` index. These are inputs to both shill scoring and ring clustering (Plan 6).
- **First measurement**: replay the 500-auction / 200-ring dataset and record recall and precision for v1. This is an
  honest early number, not the final one. The formal harness is #57 in Plan 7.
- **Dispute record creation**: the proposal's week-10 milestone mentions it. In v1, a flagged auction
  produces an alert record the adjudication flow can pick up. The full fraud-triggered dispute with evidence
  linkage is #56 in Plan 6.

### Week 10 — Demo preparation (whole team, led by Sumit)
The mid-semester demo must show, **live on the Compose stack**:
1. A seller registers → submits KYC → the admin approves → the seller lists an auction (and an unverified seller is refused)
2. Two buyers bid, with live price over WebSocket, an outbid alert, the flat fee disclosed before bidding, and anti-snipe if possible
3. The auction closes → invoice (bid + fee) → capture (mock or test-mode provider) → escrow hold visible in the ledger
4. The fraud detector flags a seeded shill pattern
5. A code walkthrough: the bid hot path, the state machines, and the append-only ledger

Tasks:
- Code freeze on **Thu Oct 8**: only bug fixes after that, on a `demo/mid-sem` release branch.
- A seed script that sets up demo users, a verified seller, auctions and a shill scenario.
- Two full rehearsals (Thu, Fri) with a timed script. Assign a presenter per segment (each member presents their component).
- Fallback plan: a recorded video of the flow in case live infrastructure fails. The paid Render tier is budgeted for
  weeks 10–11 so services don't spin down (proposal risk table).

### Week 11 — Mid-Semester Demo (Mon Oct 12) and follow-up
- Deliver the demo. Capture evaluator feedback as Jira tickets the same day.
- **Saga compensations (#63, Jaydip)**: implement the compensating action for each forward step (SDD Table 5.2): void the
  invoice and cancel the order; cancel the authorisation or fully reverse the capture; write COMPENSATION rows (never delete); revert to
  INVOICED and raise an alert. Test a failure injected at each step: no partial settlement may remain.
- **Webhooks (#64, Jaydip)**: `POST /webhooks/<provider>` with signature verification. The idempotency key per
  operation (`order:{id}:release`, and so on) means a retried webhook is a no-op.
- **Pricing coverage (#45, Sagar)**: reach ≥80% coverage and tune behaviour against replayed bid streams.

## Load warning and pull-forward
- **Harshal has 70 h in week 10 alone.** That only works if #53 and #54 were started in Plan 4 (see its
  pull-forward). If not, cut v1 scope to the three strongest signals and defer the rest to the tuning time in Plan 6.
- Week 11 is light for most members. Use it to **start Plan 6 early**, especially for Jay (95 h in Plan 6):
  audit log (#83) and dispute lifecycle spec (#84). Gaurang can start the dispute form (#73) against the SDD contract.

## Definition of done / integration gate (#107 and demo)
- [ ] The detector consumes live `bid.events` and raises `ShillAlert`s before auction close
- [ ] Fingerprint signals feed the scorer
- [ ] v1 recall and precision on the seeded dataset are recorded (target: recall ≥ 0.90 at precision ≥ 0.75)
- [ ] Stopping the detector doesn't affect bidding, and on restart it catches up from its offset
- [ ] The mid-semester demo is delivered on Oct 12 with every segment above shown
- [ ] Demo feedback is logged as tickets
- [ ] Failure injection at each Saga step leaves no partial settlement
- [ ] A duplicate webhook produces exactly one effect
- [ ] The pricing engine has ≥80% coverage

## Risks this window
| Risk | Mitigation |
|---|---|
| The live demo fails on infrastructure | Paid tier, local Compose as a backup, recorded video as a last resort |
| Detector accuracy is low in v1 | That's expected: v1 is a measurement, and tuning continues in Plan 6 against a fixed target |
| Late bug fixes break the demo | Code freeze on Oct 8, release branch, two rehearsals |
