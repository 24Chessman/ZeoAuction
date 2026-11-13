#!/usr/bin/env bash
# Plan 1 commit plan: which member commits which files, in merge order.
# Human-readable version: commits/commit-plan-01.md (same data).
#
#   bash commits/plan-01-commits.sh --check    # every Plan 1 file is in exactly one commit
#   bash commits/plan-01-commits.sh            # dry run: print each commit and its files
#   bash commits/plan-01-commits.sh --apply    # create the commits on the current branch,
#                                              # each authored by its member
#
# --apply is for replaying the Plan 1 history from one machine. In the normal team workflow,
# each member makes their own commits on their own branch and opens a PR (see the .md file).
#
# EDIT THE EMAILS BELOW first: they are the placeholders from the Jira import.
set -euo pipefail

declare -A AUTHOR=(
  [naitik]="Naitik <naitik@example.com>"
  [sumit]="Sumit <sumit@example.com>"
  [sagar]="Sagar <sagar@example.com>"
  [harshal]="Harshal <harshal@example.com>"
  [jaydip]="Jaydip <jaydip@example.com>"
  [gaurang]="Gaurang <gaurang@example.com>"
  [jay]="Jay <jay@example.com>"
  [ayush]="Ayush <ayush@example.com>"
)

# member | commit message | space-separated paths (files or directories)
PLAN=$(cat <<'EOF'
ayush|chore(repo): bootstrap repository config and tooling (#103)|.gitignore .gitattributes .editorconfig pyproject.toml requirements-dev.txt .env.example
sumit|docs(project): add proposal, system design, timeline and implementation plans (#103)|project_docs planing commits
ayush|feat(common): add zeo-common service template with health, metrics and error envelope (#88)|libs/zeo-common contracts/errors/common-error-codes.yaml
sumit|docs(contracts): add shared API components and contract rules (#28)|contracts/README.md contracts/openapi/common.v1.yaml tests/contracts/__init__.py tests/contracts/conftest.py
sumit|docs(orchestration): specify auction, order, KYC and dispute state machines (#28)|docs/state-machines.md
sumit|docs: add architecture overview, engineering conventions and ADR index (#103)|docs/architecture.md docs/engineering-conventions.md docs/adr/README.md docs/adr/0000-template.md
sumit|feat(contracts): define Kafka topic topology, AuctionStateChanged v1 and CT-1 (#28)|contracts/events/topics.yaml contracts/events/auction_state_changed.v1.json contracts/events/examples/auction_state_changed.v1.json contracts/openapi/internal/auction-state.v1.yaml
harshal|feat(contracts): freeze BidAccepted v1 and ShillAlert v1 event schemas (#50)|contracts/events/bid_accepted.v1.json contracts/events/examples/bid_accepted.v1.json contracts/events/shill_alert.v1.json contracts/events/examples/shill_alert.v1.json tests/contracts/test_event_schemas.py
jaydip|feat(contracts): add SettlementStep v1 event schema (#103)|contracts/events/settlement_step.v1.json contracts/events/examples/settlement_step.v1.json
sagar|feat(contracts): publish CT-3 minimum-increment contract (#103)|contracts/openapi/internal/pricing.v1.yaml
naitik|feat(contracts): publish bid service contract and rejection taxonomy (#18)|contracts/openapi/bid-service.v1.yaml contracts/errors/bid-rejection-codes.yaml tests/contracts/test_openapi_contracts.py
jaydip|docs(adr): propose payment provider and settlement policy, ADR-0009 and ADR-0011 (#103)|docs/adr/0009-payment-provider.md docs/adr/0011-settlement-policy.md config/settlement-policy.yaml
gaurang|docs(adr): propose notification and image-hosting approach, ADR-0010 (#103)|docs/adr/0010-third-party-services.md
ayush|docs(adr): propose repository and platform conventions, ADR-0012 (#103)|docs/adr/0012-repository-and-platform-conventions.md
ayush|feat(db): create per-service roles and schemas, auth and notify tables (#103)|infra/postgres/init/00-roles-and-schemas.sql infra/postgres/init/10-auth.sql infra/postgres/init/90-notify.sql
sagar|feat(db): add kyc, pricing and search schemas (#103)|infra/postgres/init/20-kyc.sql infra/postgres/init/50-pricing.sql infra/postgres/init/80-search.sql
sumit|feat(db): add auction schema with lifecycle audit table (#28)|infra/postgres/init/30-auction.sql
naitik|feat(db): add bids table with server_seq and idempotency constraints (#18)|infra/postgres/init/40-bid.sql
jaydip|feat(db): add payment schema with append-only escrow ledger and fee config (#103)|infra/postgres/init/60-payment.sql tests/contracts/test_settlement_policy.py
harshal|feat(db): add fraud alert and evaluation tables (#50)|infra/postgres/init/75-fraud.sql
jay|feat(db): add dispute and admin schemas with append-only audit log (#103)|infra/postgres/init/70-dispute.sql infra/postgres/init/85-admin.sql
ayush|test(db): add dev seed data and schema guard verification (#103)|infra/postgres/seed infra/postgres/verify-guards.sql
ayush|feat(services): scaffold auth-user and ws-gateway from the template (#88)|services/auth-user services/ws-gateway
naitik|feat(services): scaffold bid and escrow-sweep from the template (#88)|services/bid services/escrow-sweep
sumit|feat(services): scaffold auction-orchestrator and bid-flusher from the template (#88)|services/auction-orchestrator services/bid-flusher
sagar|feat(services): scaffold kyc, pricing and search-analytics from the template (#88)|services/kyc services/pricing services/search-analytics
jaydip|feat(services): scaffold payment-escrow from the template (#88)|services/payment-escrow
jay|feat(services): scaffold dispute and admin-moderation from the template (#88)|services/dispute services/admin-moderation
harshal|feat(services): scaffold fraud-detector from the template (#88)|services/fraud-detector
ayush|build(infra): single Docker Compose stack with Kafka, PostgreSQL, Redis and S3 storage (#88)|docker-compose.yml infra/kafka/create-topics.sh infra/s3 Makefile scripts/test-all.sh README.md
sumit|test(contracts): keep the topic contract and the topic script in sync (#28)|tests/contracts/test_topics.py
ayush|build(kafka): run Kafka as a Render private service with a persistent disk (#89)|infra/kafka/Dockerfile infra/kafka/entrypoint-render.sh infra/kafka/smoke-test.sh render.yaml
ayush|ci: run lint, unit and contract tests on every pull request (#103)|.github
EOF
)

cd "$(git rev-parse --show-toplevel)"

all_plan_paths() {
  while IFS='|' read -r _ _ paths; do
    for p in $paths; do echo "$p"; done
  done <<< "$PLAN"
}

check() {
  local failures=0
  # Every listed path must exist.
  while read -r p; do
    if [ ! -e "$p" ]; then echo "MISSING: $p"; failures=$((failures + 1)); fi
  done < <(all_plan_paths)
  # Every file in the working tree must be covered by exactly one listed path.
  local plan_paths
  plan_paths=$(all_plan_paths)
  while IFS= read -r f; do
    local hits=0
    while read -r p; do
      case "$f" in "$p"|"$p"/*) hits=$((hits + 1));; esac
    done <<< "$plan_paths"
    if [ "$hits" -ne 1 ]; then echo "COVERED $hits TIMES: $f"; failures=$((failures + 1)); fi
  done < <({ git ls-files; git ls-files --others --exclude-standard; } | sort -u)
  if [ "$failures" -eq 0 ]; then
    echo "OK: $(grep -c . <<< "$PLAN") commits cover every file exactly once."
  else
    echo "$failures problem(s)"; return 1
  fi
}

run() {
  local apply="$1" n=0
  while IFS='|' read -r member message paths; do
    n=$((n + 1))
    printf '\n[%02d] %-8s %s\n' "$n" "$member" "$message"
    # shellcheck disable=SC2086
    if [ "$apply" = yes ]; then
      git add -- $paths
      if git diff --cached --quiet; then echo "     (nothing to commit, skipped)"; continue; fi
      git commit --quiet --author="${AUTHOR[$member]}" -m "$message" -m "Plan 1 (weeks 1-2): Setup & Foundations."
      echo "     committed $(git rev-parse --short HEAD)"
    else
      for p in $paths; do echo "     + $p"; done
    fi
  done <<< "$PLAN"
}

case "${1:---dry-run}" in
  --check)   check ;;
  --dry-run) run no ;;
  --apply)   check && run yes ;;
  *)         echo "usage: $0 [--check|--dry-run|--apply]"; exit 2 ;;
esac
