## FastAPI Template Makefile

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

MAKEFLAGS += --warn-undefined-variables
MAKEFLAGS += --no-builtin-rules

.DEFAULT_GOAL := help

# Tooling commands (override from CLI if needed, e.g. `make UV=/path/to/uv test`)
UV ?= uv
PYTHON ?= python

# App runtime configuration (override for production/staging as needed)
APP_MODULE ?= main:app
HOST ?= 0.0.0.0
PORT ?= 8000
WORKERS ?= 4
SMOKE_PORT ?= 18081

# Common command arguments
COV_PATH ?= src/app
TEST_ARGS ?=
REQUIRED_TOOLS ?= $(UV)

.PHONY: \
	help check-tools install install-prod lock \
	run run-prod smoke verify-stack verify-stack-prodlike \
	db-revision db-upgrade db-downgrade \
	test test-unit test-integration coverage \
	lint lint-fix format format-check type-check \
	check ci \
	docker-build docker-push docker-up docker-up-sqlite-redis docker-up-postgres docker-up-prodlike docker-down docker-deploy-image docker-deploy-compose docker-refresh-digests \
	clean

help: ## Show available targets and descriptions
	@echo "FastAPI Template - Make targets"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' "$(lastword $(MAKEFILE_LIST))" | sort

check-tools: ## Verify required tools are installed (default: uv)
	@for tool in $(REQUIRED_TOOLS); do \
		command -v "$$tool" >/dev/null || { echo "Error: '$$tool' is not installed or not in PATH."; exit 1; }; \
	done

install: check-tools ## Install all dependencies (including dev + all extras)
	$(UV) sync --all-extras

install-prod: check-tools ## Install production dependencies only (with all extras)
	$(UV) sync --no-dev --all-extras

lock: check-tools ## Regenerate uv lockfile
	$(UV) lock

run: check-tools ## Run development server with hot reload
	$(UV) run $(PYTHON) main.py

run-prod: check-tools ## Run production server (configurable via HOST/PORT/WORKERS)
	$(UV) run uvicorn "$(APP_MODULE)" --host "$(HOST)" --port "$(PORT)" --workers "$(WORKERS)" --no-access-log

smoke: check-tools ## Run local startup smoke test on an alternate port
	$(MAKE) db-upgrade
	@APP_PORT="$(SMOKE_PORT)" $(UV) run $(PYTHON) main.py >"$$(mktemp -t fastapi-template-smoke.XXXXXX.log)" 2>&1 & \
	pid=$$!; \
	trap 'kill "$$pid" >/dev/null 2>&1 || true; wait "$$pid" >/dev/null 2>&1 || true' EXIT; \
	for _ in $$(seq 1 30); do \
		if APP_PORT="$(SMOKE_PORT)" $(UV) run $(PYTHON) ops/http_probe.py --path-env APP_HEALTH_CHECK_PATH --default-path /healthcheck >/dev/null 2>&1; then \
			break; \
		fi; \
		sleep 1; \
	done; \
	APP_PORT="$(SMOKE_PORT)" $(UV) run $(PYTHON) -c 'import os, urllib.request; port = os.environ["APP_PORT"]; response = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2); response.read(); raise SystemExit(0 if response.status == 200 else f"Unexpected status for /: {response.status}")'; \
	APP_PORT="$(SMOKE_PORT)" $(UV) run $(PYTHON) ops/http_probe.py --path-env APP_HEALTH_CHECK_PATH --default-path /healthcheck; \
	APP_PORT="$(SMOKE_PORT)" $(UV) run $(PYTHON) ops/http_probe.py --path-env APP_READINESS_CHECK_PATH --default-path /ready

verify-stack: check-tools ## Run live stack verification for DB/auth/metrics/tracing
	$(UV) run $(PYTHON) ops/test_stack.py

verify-stack-prodlike: check-tools ## Run live verification against Postgres, Redis, and JWKS
	VERIFY_STACK_DATABASE_URL="$${VERIFY_STACK_DATABASE_URL:-postgresql+asyncpg://fastapi:fastapi@127.0.0.1:5432/fastapi_template}" \
	VERIFY_STACK_ALEMBIC_DATABASE_URL="$${VERIFY_STACK_ALEMBIC_DATABASE_URL:-postgresql+psycopg://fastapi:fastapi@127.0.0.1:5432/fastapi_template}" \
	VERIFY_STACK_REDIS_URL="$${VERIFY_STACK_REDIS_URL:-redis://127.0.0.1:6379/0}" \
	VERIFY_STACK_AUTH_MODE=jwks \
	$(UV) run $(PYTHON) ops/test_stack.py

db-revision: check-tools ## Create a new Alembic revision (use MESSAGE="...")
	$(UV) run alembic -c alembic.ini revision --autogenerate -m "$(MESSAGE)"

db-upgrade: check-tools ## Apply Alembic migrations up to head
	$(UV) run alembic -c alembic.ini upgrade head

db-downgrade: check-tools ## Roll back one Alembic migration
	$(UV) run alembic -c alembic.ini downgrade -1

test: check-tools ## Run all tests (pass extra args via TEST_ARGS="...")
	$(UV) run pytest $(TEST_ARGS)

test-unit: check-tools ## Run only unit tests
	$(UV) run pytest -m unit $(TEST_ARGS)

test-integration: check-tools ## Run only integration tests
	$(UV) run pytest -m integration $(TEST_ARGS)

coverage: check-tools ## Run tests with terminal + XML coverage reports
	$(UV) run pytest --cov="$(COV_PATH)" --cov-report=term-missing --cov-report=xml $(TEST_ARGS)

lint: check-tools ## Run Ruff lint checks
	$(UV) run ruff check .

lint-fix: check-tools ## Auto-fix lint issues where possible
	$(UV) run ruff check . --fix

format: check-tools ## Format code with Ruff formatter
	$(UV) run ruff format .

format-check: check-tools ## Check code formatting without changes
	$(UV) run ruff format --check .

type-check: check-tools ## Run strict MyPy checks
	$(UV) run mypy src tests

check: ## Run local quality gate (lint + type-check + tests)
	$(MAKE) lint
	$(MAKE) type-check
	$(MAKE) test

ci: ## Run CI-quality gate (lint + format-check + type-check + tests + coverage)
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) type-check
	$(MAKE) test
	$(MAKE) coverage

docker-build: ## Build the Docker image locally
	IMAGE_NAME=$${IMAGE_NAME:-fastapi-template} PUSH_IMAGE=false ./ops/docker-build-image.sh

docker-push: ## Build and push the Docker image (set IMAGE_NAME and optional IMAGE_TAG)
	PUSH_IMAGE=true ./ops/docker-build-image.sh

docker-up: ## Start the local SQLite-only Compose stack
	docker compose up --build -d

docker-up-sqlite-redis: ## Start the local SQLite + Redis Compose stack
	docker compose -f docker-compose.yml -f docker-compose.redis.yml up --build -d

docker-up-postgres: ## Start the local Postgres-first Compose stack
	docker compose -f docker-compose.postgres.yml up --build -d

docker-up-prodlike: ## Start local Postgres + Redis Compose stack
	docker compose -f docker-compose.postgres.yml -f docker-compose.redis.yml up --build -d

docker-down: ## Stop the local Docker Compose stack
	docker compose down

docker-deploy-image: ## Deploy a published image with docker run
	./ops/docker-deploy-image.sh

docker-deploy-compose: ## Deploy a published image with docker compose
	./ops/docker-deploy-compose.sh

docker-refresh-digests: ## Refresh pinned Docker base-image digests in Dockerfile
	./ops/refresh-docker-base-digests.sh

clean: ## Remove local caches and test artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.xml
