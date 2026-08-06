PYTHON ?= python3
PNPM ?= pnpm

.PHONY: setup dev test build e2e evaluate db-bootstrap db-migrate db-seed deploy smoke prewarm demo-reset

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e 'backend[dev]'
	cd frontend && $(PNPM) install

dev:
	@echo "Run backend: .venv/bin/uvicorn app.main:app --app-dir backend --reload"
	@echo "Run frontend: cd frontend && $(PNPM) dev"

test:
	.venv/bin/ruff check backend scripts
	.venv/bin/mypy backend/app
	.venv/bin/pytest backend/tests
	cd frontend && $(PNPM) lint && $(PNPM) test

build:
	cd frontend && $(PNPM) build

.PHONY: e2e
e2e:
	cd frontend && $(PNPM) test:e2e

evaluate:
	PYTHONPATH=backend .venv/bin/python backend/evaluation/run_evaluation.py

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
