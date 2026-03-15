# Machi — AI RAG Anime Recommendation Engine

## Project Vision

Solve the problem of vague and ambiguous recommendations on current streaming platforms by building a personalized anime recommendation engine powered by RAG (Retrieval-Augmented Generation). Users submit their MyAnimeList profiles, we analyze their preferences deeply, and generate reasoned recommendations explaining *why* they'd enjoy each show — tied to specific patterns in their watch history.

---

## Architecture Overview

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│  Next.js UI  │────▶│  FastAPI Backend                              │
│             │     │  ┌──────────┐  ┌───────────┐  ┌───────────┐  │
│ • MAL Import│     │  │ MAL      │  │ Anime     │  │ RAG       │  │
│ • Dashboard │     │  │ Ingestion│  │ Knowledge │  │ Recommend │  │
│ • Recs Chat │     │  │ Service  │  │ Base      │  │ Engine    │  │
│             │     │  └────┬─────┘  └─────┬─────┘  └─────┬─────┘  │
└─────────────┘     │       │              │              │         │
                    │       ▼              ▼              ▼         │
                    │  ┌─────────┐   ┌──────────┐   ┌──────────┐   │
                    │  │ Postgres│   │ Vector DB│   │ LLM      │   │
                    │  │ (users, │   │ (Chroma/ │   │ (OpenAI) │   │
                    │  │  lists) │   │  Pgvector)│   │          │   │
                    │  └─────────┘   └──────────┘   └──────────┘   │
                    └──────────────────────────────────────────────┘
```

---

## Tech Stack

| Concern | Dev | Production |
|---|---|---|
| Database | SQLite (existing) | PostgreSQL + pgvector |
| Vector Store | ChromaDB (file-based) | pgvector or Pinecone |
| Embeddings | OpenAI `text-embedding-3-small` | Same |
| LLM | OpenAI `gpt-4o-mini` | Same |
| MAL API | Jikan v4 (free, no auth) | Jikan v4 |
| Background Jobs | Inline/async | arq + Redis |
| Caching | In-memory dict | Redis |
| Frontend | Next.js + Tailwind | Vercel |
| Backend | FastAPI + SQLAlchemy | Railway / Fly.io |

---

## Phase 1: MAL Data Ingestion & User Preference Modeling

**Goal**: Users can submit their MAL list and we store + analyze their preferences.

### Backend
1. **New Database Models** (`app/models/`)
   - `AnimeList` — links a user to their imported MAL data (mal_username, last_synced_at)
   - `AnimeEntry` — individual entries (anime_mal_id, title, user_score, watch_status, genres, synopsis, etc.)
   - `UserPreferenceProfile` — computed preference summary (favorite genres, score distributions, themes, pacing preferences)

2. **MAL Integration Service** (`app/services/mal.py`)
   - Fetch user's anime list via Jikan API v4 (https://api.jikan.moe/v4)
   - Parse: anime ID, title, score, status, episodes watched, genres, synopsis
   - Handle rate limiting (3 req/s) and pagination

3. **Preference Analysis Service** (`app/services/preference_analyzer.py`)
   - Analyze user's list to extract: genre affinity scores, average ratings by genre, preferred themes/tropes, watch patterns
   - Store as structured JSON profile

4. **API Endpoints** (`app/api/mal.py`)
   - `POST /api/mal/import` — accepts MAL username, fetches and stores their list
   - `GET /api/mal/status` — check import progress
   - `GET /api/mal/profile` — return computed preference profile

5. **Database Migration** — new tables for anime lists, entries, and preference profiles

### Frontend
6. **MAL Import Page** — input field for MAL username, import button, progress indicator
7. **Preference Dashboard** — visualize taste profile (genre radar chart, score distribution, etc.)

---

## Phase 2: Anime Knowledge Base & Vector Store (RAG Foundation)

**Goal**: Build a searchable knowledge base of anime that the LLM can retrieve from.

### Backend
1. **Anime Catalog Ingestion** (`app/services/anime_catalog.py`)
   - Bulk-fetch anime metadata from Jikan API (top anime, seasonal, by genre)
   - Target ~5,000–10,000 titles
   - Store: title, synopsis, genres, themes, studios, year, episodes, score, popularity, related anime
   - Run as background job / CLI command

2. **Vector Store Setup** (`app/services/vector_store.py`)
   - ChromaDB for dev, pgvector for production
   - For each anime: create rich text document (synopsis + genres + themes + studio + sentiment)
   - Embed using OpenAI `text-embedding-3-small`
   - Store with metadata filters (genre, year, score range)

3. **LangChain RAG Pipeline** (`app/services/rag.py`)
   - Document loader → Text splitter → Embedding → Vector store retriever
   - Custom retriever combining:
     - Semantic search (vector similarity)
     - Metadata filtering (exclude watched, filter by preferences)
     - Popularity/score weighting

### Infra
4. Add ChromaDB dependency, configure persistent storage
5. CLI command: `make ingest-anime` to populate knowledge base

---

## Phase 3: Recommendation Engine (RAG + LLM)

**Goal**: Generate personalized, reasoned anime recommendations.

### Backend
1. **Recommendation Service** (`app/services/recommender.py`)
   - User preference profile → rich prompt construction
   - Retrieve candidate anime from vector store (top 20-30)
   - LLM generates structured recommendations with specific reasoning
   - Each recommendation references shows the user liked and explains the connection

2. **Recommendation API** (`app/api/recommendations.py`)
   - `POST /api/recommendations/generate` — trigger fresh recommendations
   - `GET /api/recommendations` — get cached recommendations
   - `POST /api/recommendations/feedback` — user rates recommendations → feeds back into profile

3. **Conversational Follow-up** (`app/api/chat.py`)
   - `POST /api/chat` — streaming chat endpoint
   - Follow-up questions: "Why X?", "Something more like Y but darker", "Short and emotional"
   - LangChain conversation chain with memory + RAG retrieval

### Frontend
4. **Recommendations Page** — card layout with cover art, title, AI reasoning, feedback buttons
5. **Chat Interface** — streaming chat for conversational refinement

---

## Phase 3.5: Recommendation Persistence & Feedback Loop

**Goal**: Persist recommendations and use feedback to improve future suggestions.

### Current State (Phase 3)
- Recommendations are cached in-memory only (lost on server restart)
- Feedback (👍/👎/✅) is collected via API but stored in-memory and not used
- No history of past recommendation sessions

### Backend

1. **New Database Models** (`app/models/recommendation.py`)
   - `RecommendationSession` — stores a generation event (user_id, generated_at, custom_query, used_fallback)
   - `RecommendationEntry` — individual recommendations within a session (mal_id, title, reasoning, confidence, similar_to, scores)
   - `RecommendationFeedback` — user feedback on recommendations (mal_id, feedback_type: liked/disliked/watched, created_at)

2. **Database Migration** — new tables for recommendation history and feedback

3. **Persist Recommendations** (`app/api/recommendations.py`)
   - `POST /generate` saves the session + entries to DB (replaces in-memory cache)
   - `GET /` reads from DB instead of memory (survives restarts)
   - `GET /history` — list past recommendation sessions with timestamps

4. **Feedback-Driven Preference Tuning** (`app/services/preference_analyzer.py`)
   - "liked" feedback → boost affinity for that anime's genres/themes (+0.05 per like)
   - "disliked" feedback → reduce affinity for those genres/themes (-0.03 per dislike)
   - "watched" feedback → add to exclusion set for future recommendations
   - Store adjustments as a `feedback_adjustments` JSON field on `UserPreferenceProfile`
   - Apply adjustments during `rerank_by_preferences()` in the RAG retriever

5. **Feedback-Aware Retriever** (`app/services/rag.py`)
   - Exclude previously "disliked" mal_ids from candidates
   - Boost candidates similar to "liked" anime (higher preference_score)
   - Exclude "watched" feedback mal_ids alongside the MAL watch list

### Frontend

6. **Recommendation History** — sidebar or tab showing past sessions ("Generated 3 hours ago", "Generated yesterday")
7. **Feedback Indicators** — show which recommendations the user already rated
8. **"Regenerate with feedback"** button — explicitly uses accumulated feedback

### Why This Matters
Without feedback persistence, every "Generate" call starts from scratch.
With it, the system learns: "You liked dark thrillers and disliked romance comedies"
→ future recommendations lean harder into thrillers and away from romcoms.
This is the difference between a static tool and a learning recommendation engine.

---

## Phase 4: Polish, Testing & Production Hardening

**Goal**: Make it production-ready.

1. **Caching** — Redis/in-memory for MAL API responses and recommendations
2. **Background Jobs** — arq/celery for MAL import, catalog refresh, embedding generation
3. **Rate Limiting & Error Handling** — Jikan rate limits, OpenAI fallbacks, input validation
4. **Testing** — unit tests (preference analyzer, rec logic), integration tests (MAL pipeline), mocked LLM tests
5. **UI Polish** — loading states, error boundaries, responsive design, anime cover images
6. **Auth Flow** — smooth onboarding: login → MAL import → recommendations

---

## Phase 5: Deployment

**Goal**: Ship it.

1. **Database Migration** — SQLite → PostgreSQL + pgvector
2. **Containerization** — Dockerfiles, docker-compose for local dev
3. **CI/CD** — GitHub Actions: lint, test, build, deploy
4. **Hosting** — Backend: Railway/Fly.io, Frontend: Vercel, DB: Supabase/Neon
5. **Monitoring** — Sentry error tracking, structured logging, uptime monitoring

---

## Cost Estimates

### Development
- Jikan API: **$0** (free)
- OpenAI Embeddings: **~$0.50–2.00 total**
- OpenAI LLM: **~$1–5/month during dev**
- **Total: ~$2–7**

### Production (monthly)
- Vercel (frontend): **$0** (free tier)
- Railway/Fly.io (backend): **$5–7/mo**
- Supabase (Postgres): **$0** (free tier)
- OpenAI: **$2–10/mo** (depends on users)
- **Total: ~$5–15/mo**
