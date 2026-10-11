# Engineering conventions

These conventions are agreed in Plan 1 and apply to every member and every PR.

## Branches and commits

- `main` is protected: CI must be green and **two approvals** are required (AC-15). Nobody pushes to it directly.
- Branch names follow `<member>/<jira-id>-<short-topic>`, for example `naitik/19-bid-validation`.
- Commit messages use [Conventional Commits](https://www.conventionalcommits.org/) with the Jira id:
  `feat(bid): validate auction-open before sequencing (#19)`.
  The types are `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `ci` and `build`. The scope is the service or area name.
- Keep PRs small, one Jira task per PR where possible. Each plan's `commits/commit-plan-XX.md` lists who commits what.

## Reviews

- Every member reviews 2–3 PRs per week.
- A change to anything under `contracts/` needs approval from that contract's interface owner (`contracts/README.md`).
- A change to `infra/postgres/init/` needs approval from the owner of the affected schema.

## Python

- Python 3.11 in images and CI. Code must run on 3.11 (no newer syntax).
- `ruff check .` must pass with zero findings. The configuration is in the root `pyproject.toml`.
- Every service is created with `zeo_common.create_app`. Raise `ApiError(code, message, status)` for domain errors, and
  never return an ad-hoc error body.
- **Money is a two-decimal string at every boundary** and a `Decimal` inside the code. Never use a float.
  Use `zeo_common.parse_money` / `format_money`.
- Timestamps are timezone-aware UTC (`timestamptz`, ISO-8601 with `Z`).
- Unit tests live in `services/<name>/tests/`. **Coverage must be at least 80%** per service (enforced in CI from Plan 2).

## APIs and events

- Every route is under `/api/v1`. Breaking changes need `/api/v2` (see `contracts/README.md`).
- Endpoints that place a bid or move money take an `Idempotency-Key` header.
- Every Kafka event carries `event_id` and `schema_version`, and is keyed as `contracts/events/topics.yaml` specifies.
- Ordering within an auction comes from `server_seq`, never from timestamps.

## Data

- A service touches only its own schema. Use the owner's API, or consume their event.
- Append-only tables are never updated. A correction is a new row (for example a ledger `COMPENSATION`).
- Schema changes go in a new numbered SQL file in `infra/postgres/init/` next to the owner's file
  (for example `41-bid-increment-stale-index.sql`). Never edit a file another member has already built on.
  Locally, `make reset && make up` applies the change. How migrations are applied to the hosted database is
  decided with the Render deployment (Plan 7, #98).

## Security and privacy

- There are no secrets in the repository. Local development credentials are the only exception, and they're marked as such.
- KYC documents: use synthetic or consented samples only. Never log document bytes or signed URLs. Store object keys, not URLs.
- Payments use test mode only. The escrow is a functional simulation. Say so wherever a user might think real money is involved.

## Hours

- Log hours against Jira tasks weekly. They're audited at weeks 5, 9 and 13 against the 200-hour allocation, and work is
  reassigned if a member's variance exceeds 15%.
