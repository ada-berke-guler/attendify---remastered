COMPOSE ?= docker compose
PG_PASSWORD ?= $(or $(shell grep -E '^POSTGRES_PASSWORD=' .env 2>/dev/null | cut -d= -f2),attendify)

.PHONY: up down logs test seed reset-db tunnel web-dev

.env:
	cp .env.example .env

up: .env ## build and start everything on http://localhost
	$(COMPOSE) up --build -d
	@echo "Attendify is starting on http://localhost  (make logs to follow)"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100 api face caddy

tunnel: .env ## same as up, plus a public https URL for phones
	$(COMPOSE) --profile tunnel up --build -d
	@echo "Waiting for the tunnel URL..."
	@for i in $$(seq 1 30); do \
		url=$$($(COMPOSE) logs tunnel 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1); \
		if [ -n "$$url" ]; then echo "Open $$url on the laptop (instructor) and phone (student)"; exit 0; fi; \
		sleep 2; \
	done; echo "No URL yet, run: $(COMPOSE) logs tunnel"

seed:
	$(COMPOSE) exec api python seed.py

reset-db: ## wipe the database volume and start fresh (demo data is re-seeded)
	$(COMPOSE) down -v
	$(MAKE) up

# Runs the api test suite in a throwaway container against the compose Postgres.
test:
	$(COMPOSE) up -d db redis
	$(COMPOSE) exec db sh -c 'psql -U attendify -d attendify -tc "SELECT 1 FROM pg_database WHERE datname = '"'"'attendify_test'"'"'" | grep -q 1 || createdb -U attendify attendify_test'
	$(COMPOSE) run --rm --no-deps --user root -v "$(CURDIR)/api:/src" -w /src --entrypoint sh \
		-e TEST_DATABASE_URL=postgresql://attendify:$(PG_PASSWORD)@db:5432/attendify_test \
		-e TEST_REDIS_URL=redis://redis:6379/15 \
		api -c "pip install -q -r requirements-dev.txt && python -m pytest -q && ruff check ."
