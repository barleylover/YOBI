PYTHON ?= python3
PNPM ?= pnpm
VENV ?= $(if $(wildcard .venv/bin/python),.venv,backend/.venv)
MYPY_CACHE_DIR ?= .mypy_cache/yobi-python-3.12

.PHONY: setup dev test test-backend test-frontend build e2e evaluate db-bootstrap db-migrate db-seed deploy smoke prewarm demo-reset

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e 'backend[dev]'
	cd frontend && $(PNPM) install

dev:
	./scripts/run_local_demo.sh

test: test-backend test-frontend

test-backend:
	$(VENV)/bin/ruff check backend scripts
	$(VENV)/bin/mypy --cache-dir $(MYPY_CACHE_DIR) --python-version 3.12 backend/app backend/evaluation scripts
	$(VENV)/bin/pytest backend/tests

test-frontend:
	cd frontend && $(PNPM) lint && $(PNPM) test

build:
	cd frontend && $(PNPM) build

.PHONY: e2e
e2e:
	cd frontend && $(PNPM) test:e2e

evaluate:
	PYTHONPATH=backend $(VENV)/bin/python backend/evaluation/run_evaluation.py
	PYTHONPATH=backend $(VENV)/bin/python backend/evaluation/run_chatbot_acceptance.py

db-bootstrap:
	$(VENV)/bin/python scripts/bootstrap_db.py

db-migrate:
	$(VENV)/bin/python scripts/migrate.py

db-seed:
	$(VENV)/bin/python scripts/seed_demo.py --upsert

deploy:
	./deploy/deploy.sh

smoke:
	$(VENV)/bin/python scripts/smoke_test.py

prewarm:
	$(VENV)/bin/python scripts/prewarm.py

demo-reset:
	$(VENV)/bin/python scripts/demo_reset.py
