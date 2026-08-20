PYTHON ?= python3
PNPM ?= pnpm
VENV ?= $(if $(wildcard .venv/bin/python),.venv,backend/.venv)

.PHONY: setup dev test build e2e evaluate db-bootstrap db-migrate db-seed deploy smoke prewarm demo-reset

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e 'backend[dev]'
	cd frontend && $(PNPM) install

dev:
	./scripts/run_local_demo.sh

test:
	$(VENV)/bin/ruff check backend scripts
	$(VENV)/bin/mypy --python-version 3.12 backend/app backend/evaluation scripts
	$(VENV)/bin/pytest backend/tests
	cd frontend && $(PNPM) lint && $(PNPM) test

build:
	cd frontend && $(PNPM) build

.PHONY: e2e
e2e:
	cd frontend && $(PNPM) test:e2e

evaluate:
	PYTHONPATH=backend .venv/bin/python backend/evaluation/run_evaluation.py
	PYTHONPATH=backend .venv/bin/python backend/evaluation/run_chatbot_acceptance.py

db-bootstrap:
	.venv/bin/python scripts/bootstrap_db.py

db-migrate:
	.venv/bin/python scripts/migrate.py

db-seed:
	.venv/bin/python scripts/seed_demo.py --upsert

deploy:
	./deploy/deploy.sh

smoke:
	.venv/bin/python scripts/smoke_test.py

prewarm:
	.venv/bin/python scripts/prewarm.py

demo-reset:
	.venv/bin/python scripts/demo_reset.py
