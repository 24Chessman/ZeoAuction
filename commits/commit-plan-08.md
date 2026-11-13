# Commit plan — Plan 8: Final Delivery (week 16, Nov 16 – Nov 20)

**Status: projected.** **Milestone:** #110 *Final delivery complete*. Sumit tags `v1.0.0` on Mon Nov 16.
**Final Demo: Wed Nov 18.** After the tag, only critical fixes go in, each with two approvals, cherry-picked onto `release/v1`.

## Summary by member

| Member | Jira this plan | Commits | Focus |
|---|---|---|---|
| Gaurang | #77 (15 h) | 1 | User manual and help guide |
| Jay | #87 (10 h) | 1 | Dispute policy and admin operations guide |
| Sumit | #110 | 3 | Final results document, final demo runbook, retrospective |
| Ayush | close-out | 1 | KYC sample purge record and infrastructure scale-down |
| Naitik, Harshal, Jaydip, Sagar | results | 1 each | Their section of the final results document |

## Commits in merge order

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 1 | Sumit | `main` → tag | *(tag only)* `v1.0.0`, then branch `release/v1` | – | #110 |
| 2 | Gaurang | `gaurang/77-user-manual` | `docs(manual): user manual and help guide with UI walkthrough and simulation statement` | `docs/manual/user-manual.md`, `docs/manual/images/` | #77 |
| 3 | Jay | `jay/87-admin-guide` | `docs(manual): dispute policy and admin operations guide` | `docs/manual/admin-guide.md` | #87 |
| 4 | Naitik | `naitik/final-results-perf` | `docs(results): throughput and latency against targets` | `docs/results/performance.md` | #110 |
| 5 | Jaydip | `jaydip/final-results-settlement` | `docs(results): settlement correctness and escrow enforcement` | `docs/results/settlement.md` | #110 |
| 6 | Harshal | `harshal/final-results-fraud` | `docs(results): fraud detection recall and precision` | `docs/results/fraud.md` | #110 |
| 7 | Sagar | `sagar/final-results-kyc` | `docs(results): KYC gate and search results` | `docs/results/kyc-and-search.md` | #110 |
| 8 | Sumit | `sumit/110-final-results` | `docs(results): final results summary against every success metric` | `docs/results/README.md`, `README.md` | #110 |
| 9 | Sumit | `sumit/110-final-demo` | `docs(demo): final demo runbook with presenter per segment and fallbacks` | `docs/demo/final-script.md` | #110 |
| 10 | Ayush | `ayush/closeout` | `chore(closeout): KYC sample purge record and Render scale-down` | `docs/closeout.md`, `render.yaml` | #110 |
| 11 | Sumit | `sumit/retrospective` | `docs(project): retrospective and final hours log (200 h per member)` | `docs/progress/final-hours.md`, `docs/retrospective.md` | #110 |

Commits 2–9 land **Mon–Tue** (before the Nov 17 rehearsal), and 10–11 land **Thu–Fri** after the demo.
Commits 2–8 are documentation only, so they can merge after the `v1.0.0` tag without changing the running system.

## Gate (#110)

- [ ] `v1.0.0` live on Render and Vercel. Final demo delivered Nov 18
- [ ] The results document covers every §10 metric with measured values and evidence. Misses are reported honestly
- [ ] User manual (with the simulation statement) and admin guide submitted
- [ ] KYC samples purged. Final hours logged at 200 h per member
