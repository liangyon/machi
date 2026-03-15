.PHONY: dev backend frontend migrate migration test ingest-anime ingest-anime-all ingest-anime-all-no-embed ingest-anime-small catalog-stats embed

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

# ── Anime Knowledge Base ─────────────────────────────

## Ingest anime catalog from Jikan API + embed into vector store
## Fetches top 250 anime + 4 recent seasons (~500-700 unique anime)
ingest-anime:
	cd backend && uv run python -m app.cli ingest-anime --pages 10 --seasons 4

## Ingest the ENTIRE MAL catalog (~27,000 anime) — one-time operation
## Takes ~10-15 min to fetch + ~5 min to embed (~$0.50-1.00 OpenAI cost)
## You can split it: first run with --skip-embed, then run `make embed`
ingest-anime-all:
	cd backend && uv run python -m app.cli ingest-anime --all

## Same as above but skip embedding (fetch only, embed later with `make embed`)
ingest-anime-all-no-embed:
	cd backend && uv run python -m app.cli ingest-anime --all --skip-embed

## Quick test ingestion (2 pages = 50 anime, no embedding)
ingest-anime-small:
	cd backend && uv run python -m app.cli ingest-anime --pages 2 --seasons 0 --skip-embed

## Show catalog and vector store statistics
catalog-stats:
	cd backend && uv run python -m app.cli stats

## Embed un-embedded catalog entries into vector store
embed:
	cd backend && uv run python -m app.cli embed

# ── Testing ──────────────────────────────────────────

## Run backend tests
test:
	cd backend && uv run --extra dev pytest -v
