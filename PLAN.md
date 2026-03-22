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

### Completed (UI Polish)

1. **shadcn/ui Integration** — Initialized shadcn with base-nova style, installed 14 components (Button, Card, Input, Label, Badge, Separator, Avatar, DropdownMenu, Sheet, Skeleton, Alert, Tooltip, Sonner, NavigationMenu)
2. **Navigation System** — Persistent top navbar with:
   - Desktop: horizontal nav links (Dashboard, Recommendations, Import) with active state highlighting
   - Mobile: hamburger → Sheet drawer with same nav links
   - User dropdown menu (name, email, sign out)
   - Theme toggle (light/dark/system) via next-themes
3. **Route Groups** — Reorganized into `(app)/` (authenticated pages with navbar) and `(auth)/` (login/register with centered card layout)
4. **Emoji Removal** — All emojis replaced with Lucide icons (ThumbsUp/Down, CheckCircle, Clock, AlertTriangle, Compass, Zap, Star, Sparkles, etc.)
5. **Component Migration** — All pages migrated to shadcn components (Card, Button, Badge, Alert, Input, Label, Separator, Skeleton)
6. **Loading States** — Skeleton screens matching real layouts on all pages (navbar, dashboard stats, recommendation cards)
7. **Toast Notifications** — Sonner toasts for feedback actions, import progress, and errors
8. **Dark Mode** — Full dark mode support via next-themes with system preference detection
9. **Auth Flow** — Centralized auth guard in `(app)/layout.tsx`, smooth redirect flow

10. **Watchlist Feature** — Full to-watch list decoupled from feedback:
    - Backend: `WatchlistEntry` model with status tracking (to_watch/watching/completed/dropped), user rating (1-10), reaction/review text
    - API: GET/POST/PATCH/DELETE `/api/watchlist` endpoints
    - Recommendation cards: separate "Watchlist" bookmark button (doesn't influence algorithm) alongside feedback thumbs up/down (influences algorithm)
    - Watchlist page: status filter tabs, inline status selector, 1-10 rating widget, reaction dialog
    - Database migrations for `watchlist_entries` table
11. **Image Support** — `image_url` propagated through vector store metadata and CLI embedding pipeline for cover art on recommendation and watchlist cards
12. **Font Fix** — CSS variables moved to `html` element for proper Geist font rendering

### Remaining (Lean Phase 4 — Agreed Scope)

> **Direction chosen:** optimize for single-instance, low-traffic operation first.
> Redis/arq are explicitly **deferred** unless scaling/latency reliability triggers require them.

13. **Recommendation Loading UX (Progress Bar + Status API)**
   - `POST /api/recommendations/generate` should return quickly with `job_id`
   - Add `GET /api/recommendations/status/{job_id}` for polling (`queued/running/succeeded/failed`)
   - Track milestone progress in backend (`validate -> retrieve profile -> rerank -> LLM -> persist`)
   - Frontend recommendations page shows progress bar + stage text and transitions to results/errors

14. **Observability Baseline (Must-have)**
   - Request ID middleware and propagation in logs/responses
   - Structured logs for recommendation lifecycle and external API calls
   - Baseline metrics (latency, error rate by code, fallback rate, token usage, estimated LLM cost)
   - Minimal internal visibility surface (log summary/admin endpoint) for recent recommendation jobs

15. **LLM Cost Guardrails + Prompt Injection Safety**
   - Config-driven caps: max recommendations/request, input size limits, timeout budget
   - Guardrails for budget/limit breaches with explicit error codes
   - Prompt design with strict trusted/untrusted content boundaries
   - Never follow instructions inside retrieved synopsis/user content
   - Strict response schema validation + deterministic fallback on malformed model output

16. **Proper Error Codes + Secrets Hardening**
   - Standard API error envelope: `{ error: { code, message, details, request_id } }`
   - Stable code set (`VALIDATION_ERROR`, `RATE_LIMITED`, `UPSTREAM_TIMEOUT`, `UPSTREAM_UNAVAILABLE`, `LLM_BUDGET_EXCEEDED`, `INTERNAL_ERROR`, etc.)
   - Centralized FastAPI exception handling + consistent HTTP mappings
   - Production startup checks: reject default/weak `SECRET_KEY`, missing required provider keys
   - Ensure secrets are never logged; update `.env.example` security guidance

17. **Targeted Testing for Hardening Work**
   - Unit tests: error mapping, settings validation, guardrail enforcement, prompt sanitization/output validation
   - Integration tests: recommendation generation lifecycle + polling status flow + timeout/fallback behavior
   - Security regression tests with injection-like fixtures in MAL/user content
   - API contract tests to enforce consistent error envelope

### Deferred for Later (When Needed)

- **Redis shared cache** (defer until multi-instance or significant cache inconsistency/cost pressure)
- **arq/celery background queue** (defer until frequent long-running jobs, reliability demands, or horizontal scaling)

---

## Phase 5: Deployment

**Goal**: Ship it.

1. **Database Migration** — SQLite → PostgreSQL + pgvector
2. **Containerization** — Dockerfiles, docker-compose for local dev
3. **CI/CD** — GitHub Actions: lint, test, build, deploy
4. **Hosting** — Backend: Railway/Fly.io, Frontend: Vercel, DB: Supabase/Neon
5. **Monitoring** — Sentry error tracking, structured logging, uptime monitoring

---

## Phase 6: New Features — AniList, Cauldron, Shareable Palate Card

---

### Feature 6A: AniList Integration

**Goal**: Full AniList support as a first-class import source alongside MAL, with zero impact on the existing recommendation pipeline.

#### Why AniList Works Well Here
AniList's GraphQL API returns `idMal` on every media entry — the MAL ID. This means AniList entries can be normalized into the same `AnimeEntry` rows the rest of the system already uses. The vector store, RAG retriever, preference analyzer, and recommendation engine don't need to change at all. Only the ingestion layer is new.

#### Backend

1. **`app/services/anilist.py`** — AniList GraphQL Client
   - Endpoint: `https://graphql.anilist.co` (free, no auth for public lists)
   - Single GraphQL query fetches full user list with media metadata:
     ```graphql
     query ($username: String) {
       MediaListCollection(userName: $username, type: ANIME) {
         lists {
           entries {
             score(format: POINT_10_DECIMAL)
             status
             media {
               idMal
               title { romaji english }
               genres
               description
               averageScore
               startDate { year }
               studios { nodes { name } }
               tags { name rank }
               coverImage { large }
             }
           }
         }
       }
     }
     ```
   - Map AniList statuses → MAL statuses (`COMPLETED → completed`, `CURRENT → watching`, `PLANNING → plan_to_watch`, `DROPPED → dropped`, `PAUSED → on_hold`)
   - Skip entries where `idMal` is null (AniList-exclusive titles with no MAL ID) — log and count skips
   - Rate-limit aware (AniList: 90 req/min)

2. **`app/models/anime.py`** — Schema Extension
   - Add `source` column to `AnimeList` (`mal` | `anilist`, default `mal`)
   - Add `anilist_username` nullable column to `AnimeList`
   - No changes to `AnimeEntry` — `mal_id` stays the universal key

3. **`app/api/anilist.py`** — New Router
   - `POST /api/anilist/import` — accepts `{ anilist_username }`, fetches and stores list, triggers preference analysis
   - `GET /api/anilist/status` — same job-polling contract as `/mal/status`
   - Register under central router as `/api/anilist`

4. **Migration** — Add `source` + `anilist_username` to `anime_lists` table

#### Frontend

5. **Import Page** — Add AniList import card alongside the existing MAL card
   - Same UX: username input, import button, progress bar, success state
   - Show AniList logo/branding on the card

6. **Dashboard** — Show `source` badge on the imported list section (`MyAnimeList` vs `AniList`)

#### Compatibility Checklist
- Preference analyzer: no changes (reads `AnimeEntry` rows, source-agnostic)
- RAG retriever: no changes (uses `mal_id` for filtering)
- Vector store: no changes (keyed on `mal_id`)
- Recommendation engine: no changes
- Watchlist: no changes (watchlist entries use `mal_id`)
- Feedback: no changes

#### Edge Cases
- User imports AniList and then tries to import MAL (or vice versa): allow both, merge entries by `mal_id` (update existing row on conflict)
- AniList entry has no `idMal`: skip silently, include count in import response (`skipped_no_mal_id: N`)
- AniList score of 0 = unscored, same as MAL's 0 — exclude from avg-score computation but include in frequency

---

### Feature 6B: Cauldron

**Goal**: A second recommendation mode where users pick 1–3 "seed" shows and get 5 recommendations that scratch the exact same itch — no profile required.

#### Concept
The Cauldron is vibe-matching. You don't need a full MAL/AniList import. You say "I want more of what made *Vinland Saga*, *Berserk*, and *Kingdom* feel so good" and it finds 5 shows with that exact DNA. The LLM is given the seeds' metadata and tasked with reasoning about what makes them tick, then hunting for matches.

#### Backend

1. **`app/services/cauldron.py`** — Core Logic
   - `generate_cauldron_recs(seed_mal_ids: list[int], user_id: int | None) → list[Recommendation]`
   - Step 1: Fetch seed metadata from `anime_catalog` table (already have it) or Jikan if missing
   - Step 2: Build a "blend profile" from seeds:
     - Union of genres/themes with frequency weighting
     - Composite description: "Show 1 is known for X, Show 2 for Y..."
   - Step 3: Multi-query RAG retrieval using seed titles + genre blend
     - Exclude the seed shows themselves from results
     - Optionally exclude user's watched list if `user_id` provided
   - Step 4: LLM prompt explaining the seeds and asking for 5 recommendations from the retrieved candidates
     - Prompt instructs: "Explain which aspect of the seeds each pick captures"
   - Step 5: Parse and return (same schema as regular recommendations — `RecommendationEntry`)

2. **`app/api/cauldron.py`** — Router
   - `POST /api/cauldron/generate`
     - Body: `{ seed_ids: [mal_id, ...], user_id?: int }` (1–3 seeds, validated)
     - Returns: job_id for async polling (same pattern as `/recommendations/generate`)
   - `GET /api/cauldron/status/{job_id}` — standard polling endpoint
   - `GET /api/cauldron/search?q=...` — anime title search to help users find seeds
     - Searches `anime_catalog` table by title (ILIKE), returns top 10 matches with cover art

3. **`app/api/cauldron.py`** — Anime Search (for Seed Picker)
   - `GET /api/cauldron/search?q={query}` — simple title search against `anime_catalog`
   - Returns: `[ { mal_id, title, image_url, year, genres[] } ]`
   - If catalog doesn't have the anime: fallback to Jikan search

4. **Persistence** — Cauldron results saved into `RecommendationSession` with a `mode: "cauldron"` field and `seed_ids` in the session metadata. Reuses the same `RecommendationEntry` table.
   - Add `mode` (`standard` | `cauldron`) and `cauldron_seed_ids` (JSON array) to `RecommendationSession`
   - Migration required

#### Frontend

5. **`/cauldron` Page** — New protected route under `(app)/`
   - Layout: a centered "cauldron" metaphor UI (the name should feel a little witchy/alchemical)
   - **Seed Picker**: searchable anime picker, max 3 slots shown as cards with cover art
     - Inline search (debounced, hits `/api/cauldron/search`)
     - Each slot shows the selected show's cover + title with an X to remove
   - **"Brew" button**: disabled until ≥1 seed selected; triggers generation
   - **Progress bar**: same polling UX as the main recommendations page
   - **Results**: 5 recommendation cards, same `RecommendationCard` component as main recs
     - Each card's reasoning should reference which seed it connects to
   - No MAL/AniList import required — fully standalone feature

6. **Navbar** — Add "Cauldron" link to the navigation

#### Prompt Design Notes
- Seeds are provided in full (title, genres, synopsis excerpt, themes)
- Candidates are provided as the pool to pick from
- Prompt asks the LLM to name what "essence" each seed has (e.g., "slow-burn political intrigue", "brutal coming-of-age") before picking recommendations
- This forces the LLM to reason about the blend, not just genre-match

---

### Feature 6C: Shareable Palate Card

**Goal**: A beautiful, shareable image card that roasts the user's taste while flattering it — a snapshot of their anime identity with personality.

#### Card Contents
| Section | Content |
|---|---|
| **Top Genres** | 3–5 genre badges sized by affinity score |
| **Favorite Era** | Which decade they watch most (e.g., "2010s maximalist") |
| **Dark Horse** | Highest user-rated show with community score < 7.5 (MAL avg) — "You gave X a 10. The internet gave it a 7.3. Taste." |
| **Archetype Title** | LLM-generated label: e.g., *"The Contrarian"*, *"Shonen Tourist"*, *"Certified Art Film Goblin"* |
| **Taste Traits** | 3–4 short trait chips: e.g., "completes everything", "underdog enjoyer", "skips slice-of-life" |
| **One-liner** | LLM-generated smug/funny line about their taste. Mean but loving. |
| **Source Badge** | Small MAL or AniList logo + username |

#### Backend

1. **`app/services/palate_card.py`** — Analysis + Generation
   - `generate_palate_card(user_id: int) → PalateCardData`
   - Reads from existing `UserPreferenceProfile` (already computed)
   - Additional computations (pure, over the user's `AnimeEntry` rows):
     - **Era**: group entries by `start_year // 10 * 10`, find peak decade
     - **Dark horse**: filter entries where `user_score >= 9` and `community_score < 7.5`, pick highest user-scored
     - **Taste traits**: rule-based from profile data:
       - Completion rate > 85% → "completes everything"
       - Score variance high → "harsh rater"
       - Avg score > 8 → "generous scorer"
       - Top genre is niche (Psychological, Seinen, etc.) → "certified taste"
       - Many entries with 0 score → "watches without judging"
   - LLM call (single, cheap) for archetype + one-liner:
     - Input: top genres, era, dark horse title, 3 taste traits, completion rate, avg score
     - Output: `{ archetype: str, one_liner: str }` — JSON response
     - Temperature: 0.9 (for personality)
     - Max tokens: 100 (cheap — this is a tiny prompt)

2. **`app/api/profile.py`** — New or Extended Router
   - `GET /api/profile/palate-card` — generate + return `PalateCardData`
   - Cache result per user with 1h TTL (palate doesn't change fast; LLM call cost)
   - Response schema:
     ```json
     {
       "username": "...",
       "source": "mal" | "anilist",
       "top_genres": [{ "name": "...", "affinity": 0.87 }],
       "favorite_era": "2010s",
       "dark_horse": { "title": "...", "user_score": 10, "community_score": 7.1 },
       "archetype": "The Contrarian",
       "taste_traits": ["completes everything", "harsh rater"],
       "one_liner": "You've seen 300 shows and somehow still think popular = bad.",
       "entry_count": 312,
       "avg_score": 7.4
     }
     ```

#### Frontend

3. **`/palate` Page** — New protected route under `(app)/`
   - Renders the card from the API response
   - Card is a styled `div` (not canvas) — designed to be screenshot-able or export as PNG
   - **Export as PNG**: use `html2canvas` (or `dom-to-image-more`) to capture the card `div`
   - **Share flow**: download PNG → user posts to socials manually (no third-party API needed)
   - Loading state: show skeleton card while generating
   - "Regenerate" button (clears cache on backend, forces fresh LLM call)

4. **Card Visual Design**
   - Dark card (works well for social sharing)
   - Large archetype title as the hero text
   - Genre bars or bubbles
   - One-liner in italic, slightly smaller
   - Machi branding in corner
   - Clean, no clutter — meant to be a screenshot

5. **Navbar** — Add "Palate" link to navigation (or nest under user dropdown as "My Palate Card")

#### Archetype & One-liner Prompt Notes
Sample LLM prompt structure:
```
You are a smug anime critic writing a funny, roast-style taste label for a user.
Top genres: Action, Psychological, Thriller
Favorite era: 2000s
Dark horse: Serial Experiments Lain (they rated it 10, avg is 6.8)
Traits: completes everything, harsh rater, niche taste

Give them:
- An archetype title (2–4 words, creative, slightly mean)
- A one-liner (under 20 words, smug but fond, like a friend roasting you)

Respond in JSON: { "archetype": "...", "one_liner": "..." }
```

---

### Implementation Order

| Priority | Feature | Effort | Notes |
|---|---|---|---|
| 1 | AniList Integration | Medium | Unlocks more users; zero risk to existing pipeline |
| 2 | Palate Card | Medium | High shareability/viral potential; mostly reads from existing data |
| 3 | Cauldron | High | New recommendation surface; requires search UI + new prompt design |

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
