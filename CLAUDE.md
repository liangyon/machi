# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Machi is a RAG-powered anime recommendation engine. Users import MyAnimeList/AniList profiles, which are analyzed to build taste profiles. A RAG pipeline (LangChain + ChromaDB + OpenAI) retrieves candidate anime and an LLM generates personed recommendations with reasoning.

## Commands

All commands are defined in the root `Makefile`.

### Development
```bash
make dev              # Run backend (port 8000) + frontend (port 3000) concurrently
make backend          # FastAPI only: cd backend && uv run uvicorn app.main:app --reload
make frontend         # Next.js only: cd frontend && pnpm dev
```

### Database
```bash
make migrate                          # Apply pending Alembic migrations
make migration msg="description"      # Auto-generate a new migration
```

### Testing
```bash
make test                             # Run all backend tests (pytest)
cd backend && uv run --extra dev pytest tests/path/test_file.py -v   # Single test file
cd backend && uv run --extra dev pytest -k "test_name" -v            # Single test by name
```

### Anime Knowledge Base Ingestion
```bash
make ingest-anime         # Fetch top ~500-700 anime + embed into vector store
make ingest-anime-all     # Full MAL catalog (~27k anime, ~$0.50-1.00 OpenAI cost)
make embed                # Embed un-embedded catalog entries
make catalog-stats        # Show catalog + vector store statistics
```

### Frontend
```bash
cd frontend && pnpm build    # Production build
cd frontend && pnpm lint     # ESLint
```

## Architecture

**Monorepo with two services:**
- `frontend/` — Next.js 16 (React 19, TypeScript, Tailwind CSS 4, shadcn/ui)
- `backend/` — FastAPI (Python 3.11+, SQLAlchemy 2, Alembic, LangChain)

### Backend (`backend/app/`)

- `api/` — Route handlers. Each file is a FastAPI router mounted via `api/router.py`. Auth dependencies are in `api/deps.py`.
- `services/` — Business logic layer. Key services:
  - `recommender.py` — LLM-based recommendation generation (main pipeline)
  - `cauldron.py` — Seed-based "vibe matching" recommendations
  - `rag.py` — RAG retrieval pipeline
  - `vector_store.py` — ChromaDB wrapper
  - `preference_analyzer.py` — Computes user taste profiles from watch history
  - `auth.py` — JWT, bcrypt, OAuth provider setup
  - `mal.py` / `anilist.py` — External API integrations (Jikan REST / AniList GraphQL)
- `models/` — SQLAlchemy ORM models (User, AnimeEntry, AnimeCatalogEntry, RecommendationSession, WatchlistEntry, etc.)
- `schemas/` — Pydantic request/response schemas
- `core/config.py` — Centralized settings via pydantic-settings (reads `.env`)
- `cli.py` — CLI commands for anime catalog ingestion (`python -m app.cli`)

### Frontend (`frontend/`)

- `app/(app)/` — Protected routes (dashboard, recommendations, cauldron, discover, watchlist, import). Layout includes auth guard + navbar.
- `app/(auth)/` — Public routes (login, register)
- `lib/api.ts` — Centralized fetch client for all backend calls
- `lib/auth-context.tsx` — AuthProvider + `useAuth()` hook (React Context)
- `lib/types.ts` — Shared TypeScript interfaces
- `components/ui/` — shadcn/ui primitives (base-nova style)

### Key Patterns

- **Long-running operations** (recommendations, cauldron) use a job-polling pattern: POST to start → returns job ID → client polls GET status endpoint.
- **Dev API proxy**: Next.js rewrites `/api/*` to `localhost:8000` in dev. In production, `NEXT_PUBLIC_API_URL` points directly to the backend.
- **Dev vs Prod divergence**: SQLite + ChromaDB locally; PostgreSQL + pgvector in production.
- **Frontend path alias**: `@/*` maps to the `frontend/` root.

### Environment

Backend requires `OPENAI_API_KEY` in `backend/.env`. OAuth needs `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`. See `backend/app/core/config.py` for all settings. Root `.env.example` is for Docker Compose only.

## Deployment

- **Frontend**: Vercel
- **Backend**: Railway (Docker)
- **Database**: Neon (PostgreSQL + pgvector)
- CI/CD via GitHub Actions (`.github/workflows/`): backend tests, frontend lint+build, Docker build check on PR; auto-deploy on push to main.
