# DJ Hub. Run `make setup` once, then `make start` (or `make dev` while changing code).
SHELL := /bin/bash
HOST := 127.0.0.1
PORT := 8000

.PHONY: setup dev start build test lint import-legacy migration

setup:
	uv sync --project backend
	npm --prefix frontend install

# API with auto-reload on :8000 and the Vite dev server on :5173 (open http://127.0.0.1:5173).
# Note: a code change restarts the API and interrupts a running job (resume it from History).
dev:
	@trap 'kill 0' EXIT; \
	DJ_HUB_FRONTEND=http://$(HOST):5173 uv run --directory backend \
		uvicorn app.main:app --host $(HOST) --port $(PORT) --reload & \
	npm --prefix frontend run dev & \
	wait

# One server on :8000 serving the built frontend (open http://127.0.0.1:8000).
start: build
	uv run --directory backend uvicorn app.main:app --host $(HOST) --port $(PORT)

build:
	npm --prefix frontend run build

test:
	uv run --directory backend pytest -q
	npm --prefix frontend run build

lint:
	uv run --directory backend ruff check .
	npm --prefix frontend run lint

import-legacy:
	uv run --directory backend djhub import-legacy

# After changing backend/app/models.py: make migration m="what changed"
migration:
	cd backend && uv run alembic revision --autogenerate -m "$(m)" && rm -f .alembic-scratch.db
