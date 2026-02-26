.PHONY: dev backend frontend migrate migration test

# ── Development ──────────────────────────────────────

## Run both backend and frontend concurrently
dev:
	@echo "Starting backend & frontend…"
	@make -j2 backend frontend

## Start the FastAPI backend (port 8000)
backend:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

## Start the Next.js frontend (port 3000)
frontend:
	cd frontend && pnpm dev

# ── Database ─────────────────────────────────────────

## Apply all pending migrations
migrate:
	cd backend && uv run alembic upgrade head

## Create a new migration (usage: make migration msg="add users table")
migration:
	cd backend && uv run alembic revision --autogenerate -m "$(msg)"

# ── Testing ──────────────────────────────────────────

## Run backend tests
test:
	cd backend && uv run --extra dev pytest -v
