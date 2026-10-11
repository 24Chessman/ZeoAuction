# Developer shortcuts (owner: Ayush). On Windows without make, run the command after each
# target directly, e.g. `docker compose up -d --build`.
.PHONY: up down reset ps logs seed verify-db topics smoke-kafka lint test test-contracts config

up:            ## Build and start the whole stack
	docker compose up -d --build

down:          ## Stop the stack, keep data
	docker compose down

reset:         ## Stop and delete all data volumes (re-runs the schema init scripts)
	docker compose down -v

ps:            ## Show container health
	docker compose ps

logs:          ## Follow logs of every service
	docker compose logs -f --tail=100

seed:          ## Load development fixtures (idempotent)
	docker compose exec -T postgres psql -U postgres -d zeoauction -v ON_ERROR_STOP=1 -f /seed/dev-seed.sql

verify-db: seed ## Prove schema guarantees: ownership, append-only, single terminal row
	docker compose exec -T postgres psql -U postgres -d zeoauction -f /verify/verify-guards.sql

topics:        ## List Kafka topics
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe

smoke-kafka:   ## Produce, restart the broker, verify persistence
	docker compose exec -e SMOKE_MARKER_FILE=/var/lib/kafka/data/.smoke-marker kafka sh /opt/zeo/smoke-test.sh produce localhost:9092
	docker compose restart kafka
	docker compose exec -e SMOKE_MARKER_FILE=/var/lib/kafka/data/.smoke-marker kafka sh -c 'until /opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092 >/dev/null 2>&1; do sleep 2; done; sh /opt/zeo/smoke-test.sh verify localhost:9092'

lint:          ## Ruff over the whole repository
	ruff check .

test:          ## Shared library, contracts and every service's unit tests
	sh scripts/test-all.sh

test-contracts:
	pytest tests/contracts

config:        ## Validate docker-compose.yml
	docker compose config --quiet
