# Smart Café Vision — common operations.
#
# Every target works on a fresh clone. Where a target needs the virtualenv it
# uses it explicitly, so nothing depends on the caller having activated it.

PYTHON := .venv/Scripts/python.exe
ifeq ($(OS),)
	PYTHON := .venv/bin/python
endif

.PHONY: help
help:
	@echo "Setup"
	@echo "  make install         Install backend, worker and frontend dependencies"
	@echo "  make env             Create .env from .env.example with generated keys"
	@echo ""
	@echo "Run (Docker)"
	@echo "  make up              Start the full stack"
	@echo "  make down            Stop the stack"
	@echo "  make logs            Follow all logs"
	@echo "  make bootstrap       Create the first café and owner account"
	@echo ""
	@echo "Production"
	@echo "  make backup          Back up the database (scripts/backup.sh)"
	@echo "  make restore FILE=backups/smartcafe-<timestamp>.sql.gz"
	@echo "                       Restore the database from a backup"
	@echo ""
	@echo "Run (local, no Docker)"
	@echo "  make backend         Run the API + websockets on :8000"
	@echo "  make consumer        Run the event bus consumer"
	@echo "  make frontend        Run the dashboard on :3000"
	@echo ""
	@echo "Quality"
	@echo "  make test            Run every test suite"
	@echo "  make lint            Lint backend and frontend"
	@echo "  make check           Django system checks + migration drift"

.PHONY: install
install:
	$(PYTHON) -m pip install -r backend/requirements/dev.txt
	$(PYTHON) -m pip install -e ./shared
	cd frontend && npm install

.PHONY: env
env:
	@test -f .env || cp .env.example .env
	@$(PYTHON) scripts/generate_keys.py

.PHONY: up
up:
	docker compose up -d --build

.PHONY: down
down:
	docker compose down

.PHONY: logs
logs:
	docker compose logs -f

.PHONY: bootstrap
bootstrap:
	docker compose run --rm backend python manage.py bootstrap --email $(EMAIL)

.PHONY: backup
backup:
	./scripts/backup.sh

.PHONY: restore
restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/smartcafe-<timestamp>.sql.gz"; exit 1)
	./scripts/restore.sh $(FILE)

.PHONY: backend
backend:
	cd backend && ../$(PYTHON) manage.py runserver 0.0.0.0:8000

.PHONY: consumer
consumer:
	cd backend && ../$(PYTHON) manage.py consume_events

.PHONY: frontend
frontend:
	cd frontend && npm run dev

.PHONY: test
test: test-backend test-worker test-frontend

.PHONY: test-backend
test-backend:
	cd backend && ../$(PYTHON) -m pytest

.PHONY: test-worker
test-worker:
	cd ai_worker && ../$(PYTHON) -m pytest

.PHONY: test-frontend
test-frontend:
	cd frontend && npm run typecheck

.PHONY: lint
lint:
	$(PYTHON) -m ruff check backend ai_worker shared
	cd frontend && npm run lint

.PHONY: check
check:
	cd backend && ../$(PYTHON) manage.py check
	cd backend && ../$(PYTHON) manage.py makemigrations --check --dry-run
