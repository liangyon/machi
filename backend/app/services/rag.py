"""RAG retriever — the bridge between vector search and recommendations.

This module sits between the raw vector store (Step 5) and the
recommendation engine (Phase 3).  It adds "intelligence" on top of
semantic search by:

1. **Auto-generating search queries** from a user's preference profile
2. **Excluding watched anime** so we never recommend what they've seen
3. **Applying preference-based filters** (genre, era, quality)
4. **Re-ranking results** by combining similarity with preference fit

Why a separate retriever layer?
───────────────────────────────
The vector store does raw semantic search — "find anime whose
descriptions are similar to this text."  But good recommendations
need more:

• A user who loves "dark psychological thrillers" shouldn't get
  results they've already watched.
• A user who rates action anime 8+ but romance anime 5 should
  see more action candidates.
• The search query itself should be *constructed* from the user's
  taste profile, not typed manually.

This retriever handles all of that.  Phase 3's recommendation engine
will call ``retrieve_candidates()`` and feed the results to the LLM
for final reasoning and explanation.

Design decisions
────────────────
1. **Multiple search queries** — We generate several queries from
   different angles of the user's profile (top genres, favorite
   shows, themes) and merge results.  This gives broader coverage
   than a single query.

2. **Watched anime exclusion** — We pass the user's watched MAL IDs
   and filter them out post-retrieval (ChromaDB doesn't support
   "NOT IN" filters on metadata, so we filter in Python).

3. **Preference-weighted re-ranking** — After vector search, we
   boost results that align with the user's genre/theme preferences.
   This combines semantic similarity (from embeddings) with
   collaborative signals (from their watch history).

4. **Pure functions where possible** — Query building and re-ranking
   are pure functions, easy to test without a vector store.
"""

from __future__ import annotations

from app.core.logging import logger
from app.services.vector_store import search_anime


# ═════════════════════════════════════════════════════════
# Main retrieval function
# ═════════════════════════════════════════════════════════


def retrieve_candidates(
    preference_profile: dict,
    watched_mal_ids: set[int] | None = None,
    k: int = 30,
    min_score: float | None = 7.0,
    custom_query: str | None = None,
) -> list[dict]:
    """Retrieve anime candidates for recommendation.

    This is the main entry point for Phase 3's recommendation engine.
    It generates search queries from the user's profile, searches the
    vector store, excludes watched anime, and re-ranks by preference
    alignment.

    Args:
        preference_profile: The user's computed preference profile
            (from ``UserPreferenceProfile.profile_data``).
        watched_mal_ids: Set of MAL IDs the user has already watched.
            These will be excluded from results.
        k: Number of candidates to return (default 30).
        min_score: Minimum MAL community score filter (default 7.0).
            Set to None to disable.
        custom_query: Optional custom search query (overrides auto-
            generated queries).  Used for conversational follow-ups
            like "something darker" or "more like Steins;Gate".

    Returns:
        List of candidate dicts, sorted by combined score (descending).
        Each dict contains:
        - ``mal_id``: int
        - ``title``: str
        - ``embedding_text``: str
        - ``metadata``: dict
        - ``similarity_score``: float (from vector search)
        - ``preference_score``: float (from re-ranking)
        - ``combined_score``: float (weighted combination)
    """
    watched_mal_ids = watched_mal_ids or set()

    # Build metadata filter
    filter_dict = {}
    if min_score is not None:
        filter_dict["mal_score_gte"] = min_score

    # Generate search queries
    if custom_query:
        queries = [custom_query]
    else:
        queries = build_search_queries(preference_profile)

    if not queries:
        logger.warning("No search queries generated from profile")
        return []

    # Search with each query and merge results
    # We fetch more than k per query because we'll deduplicate and filter
    fetch_k = min(k * 2, 50)  # fetch extra to account for filtering
    all_results: dict[int, dict] = {}  # mal_id → best result

    for query in queries:
        results = search_anime(
            query=query,
            k=fetch_k,
            filter_dict=filter_dict if filter_dict else None,
        )

        for result in results:
            mal_id = result.get("mal_id", 0)

            # Skip watched anime
            if mal_id in watched_mal_ids:
                continue

            # Keep the result with the highest similarity score
            if mal_id not in all_results or result["similarity_score"] > all_results[mal_id]["similarity_score"]:
                all_results[mal_id] = result

    # Re-rank by preference alignment
    candidates = list(all_results.values())
    candidates = rerank_by_preferences(candidates, preference_profile)

    # Sort by combined score and return top k
    candidates.sort(key=lambda x: x.get("combined_score", 0), reverse=True)
    return candidates[:k]


# ═════════════════════════════════════════════════════════
# Query generation — turns a preference profile into
# natural language search queries
# ═════════════════════════════════════════════════════════


def build_search_queries(profile: dict) -> list[str]:
    """Generate search queries from a user's preference profile.

    We create multiple queries from different angles to get broad
    coverage.  Each query targets a different aspect of the user's
    taste:

    1. **Genre-based query** — "Action, Sci-Fi anime with high ratings"
    2. **Top shows query** — "anime similar to [their top-rated shows]"
    3. **Theme-based query** — "anime with themes of Space, Psychology"

    Why multiple queries?
    A single query might miss good candidates.  Someone who loves
    both "dark psychological thrillers" and "wholesome slice of life"
    needs queries for both.  We merge and deduplicate results.

    Args:
        profile: The user's preference profile dict.

    Returns:
        List of 1-3 natural language query strings.
    """
    queries: list[str] = []

    # ── Query 1: Top genres ──────────────────────────────
    genre_query = _build_genre_query(profile)
    if genre_query:
        queries.append(genre_query)

    # ── Query 2: Similar to top shows ────────────────────
    top_shows_query = _build_top_shows_query(profile)
    if top_shows_query:
        queries.append(top_shows_query)

    # ── Query 3: Theme-based ─────────────────────────────
    theme_query = _build_theme_query(profile)
    if theme_query:
        queries.append(theme_query)

    # Fallback: if no queries could be generated
    if not queries:
        queries.append("highly rated popular anime")

    return queries


# ═════════════════════════════════════════════════════════
# Re-ranking — combines vector similarity with preference
# alignment for better recommendations
# ═════════════════════════════════════════════════════════


def rerank_by_preferences(
    candidates: list[dict],
    profile: dict,
) -> list[dict]:
    """Re-rank candidates by combining similarity with preference fit.

    The vector store gives us semantic similarity (how close the
    anime's description is to the query).  But we also want to
    factor in the user's actual preferences:

    - Does this anime's genre match their high-affinity genres?
    - Is it from an era they tend to watch?
    - Is it the type of format they prefer (TV vs Movie)?

    We compute a ``preference_score`` (0–1) and combine it with
    the ``similarity_score`` using a weighted formula:

        combined = 0.6 × similarity + 0.4 × preference

    Why 60/40?  Semantic similarity should dominate (it captures
    the "vibe" of what they like), but preference alignment is a
    useful tiebreaker and quality signal.

    Args:
        candidates: List of search result dicts.
        profile: The user's preference profile.

    Returns:
        Same list with ``preference_score`` and ``combined_score`` added.
    """
    # Extract user's genre preferences as a lookup
    genre_affinities = _get_genre_affinity_map(profile)
    theme_affinities = _get_theme_affinity_map(profile)
    preferred_formats = profile.get("preferred_formats", {})
    era_prefs = profile.get("watch_era_preference", {})

    for candidate in candidates:
        metadata = candidate.get("metadata", {})
        pref_score = _compute_preference_score(
            metadata=metadata,
            genre_affinities=genre_affinities,
            theme_affinities=theme_affinities,
            preferred_formats=preferred_formats,
            era_prefs=era_prefs,
        )

        candidate["preference_score"] = round(pref_score, 4)

        # Combined score: weighted blend of similarity and preference
        sim_score = candidate.get("similarity_score", 0)
        candidate["combined_score"] = round(
            0.6 * sim_score + 0.4 * pref_score, 4
        )

    return candidates


# ═════════════════════════════════════════════════════════
# Private helpers — query building
# ═════════════════════════════════════════════════════════


def _build_genre_query(profile: dict) -> str | None:
    """Build a search query from the user's top genres.

    Takes the top 3 genres by affinity and constructs a query like:
    "Action, Sci-Fi, Thriller anime with compelling stories"
    """
    genre_affinity = profile.get("genre_affinity", [])
    if not genre_affinity:
        return None

    # Take top 3 genres by affinity score
    top_genres = [g["genre"] for g in genre_affinity[:3]]
    if not top_genres:
        return None

    genre_str = ", ".join(top_genres)
    return f"{genre_str} anime with compelling stories and high quality"


def _build_top_shows_query(profile: dict) -> str | None:
    """Build a search query from the user's top-rated shows.

    Takes their top 3 shows and constructs a query like:
    "anime similar to Steins;Gate, Death Note, and Monster"
    """
    top_10 = profile.get("top_10", [])
    if not top_10:
        return None

    # Take top 3 shows
    top_titles = [show.get("title", "") for show in top_10[:3] if show.get("title")]
    if not top_titles:
        return None

    titles_str = ", ".join(top_titles)
    return f"anime similar to {titles_str}"


def _build_theme_query(profile: dict) -> str | None:
    """Build a search query from the user's top themes.

    Takes the top 3 themes by affinity and constructs a query like:
    "anime with themes of Time Travel, Psychological, Military"
    """
    theme_affinity = profile.get("theme_affinity", [])
    if not theme_affinity:
        return None

    top_themes = [t["genre"] for t in theme_affinity[:3]]
    if not top_themes:
        return None

    theme_str = ", ".join(top_themes)
    return f"anime with themes of {theme_str}"


# ═════════════════════════════════════════════════════════
# Private helpers — preference scoring
# ═════════════════════════════════════════════════════════


def _get_genre_affinity_map(profile: dict) -> dict[str, float]:
    """Convert genre_affinity list to a {genre: affinity} lookup."""
    return {
        g["genre"]: g.get("affinity", 0)
        for g in profile.get("genre_affinity", [])
    }


def _get_theme_affinity_map(profile: dict) -> dict[str, float]:
    """Convert theme_affinity list to a {theme: affinity} lookup."""
    return {
        t["genre"]: t.get("affinity", 0)
        for t in profile.get("theme_affinity", [])
    }


def _compute_preference_score(
    metadata: dict,
    genre_affinities: dict[str, float],
    theme_affinities: dict[str, float],
    preferred_formats: dict[str, int],
    era_prefs: dict[str, int],
) -> float:
    """Compute how well an anime matches the user's preferences.

    Returns a score from 0.0 to 1.0 based on:
    - Genre match (40% weight) — do the anime's genres match high-affinity genres?
    - Theme match (20% weight) — do the themes align?
    - Format match (20% weight) — is it a format they watch (TV, Movie)?
    - Era match (20% weight) — is it from a decade they tend to watch?

    Each component is normalised to 0–1 before weighting.
    """
    scores: list[tuple[float, float]] = []  # (score, weight)

    # ── Genre match (40%) ────────────────────────────────
    genres_str = metadata.get("genres", "")
    if genres_str and genre_affinities:
        anime_genres = [g.strip() for g in genres_str.split(",")]
        genre_scores = [
            genre_affinities.get(g, 0) for g in anime_genres
        ]
        # Average affinity of matching genres
        genre_score = sum(genre_scores) / len(genre_scores) if genre_scores else 0
        scores.append((genre_score, 0.4))
    else:
        scores.append((0.5, 0.4))  # neutral if no data

    # ── Theme match (20%) ────────────────────────────────
    themes_str = metadata.get("themes", "")
    if themes_str and theme_affinities:
        anime_themes = [t.strip() for t in themes_str.split(",")]
        theme_scores = [
            theme_affinities.get(t, 0) for t in anime_themes
        ]
        theme_score = sum(theme_scores) / len(theme_scores) if theme_scores else 0
        scores.append((theme_score, 0.2))
    else:
        scores.append((0.5, 0.2))  # neutral if no data

    # ── Format match (20%) ───────────────────────────────
    anime_type = metadata.get("anime_type", "")
    if anime_type and preferred_formats:
        total_formats = sum(preferred_formats.values())
        format_ratio = preferred_formats.get(anime_type, 0) / total_formats if total_formats else 0
        scores.append((min(format_ratio * 2, 1.0), 0.2))  # scale up, cap at 1
    else:
        scores.append((0.5, 0.2))

    # ── Era match (20%) ──────────────────────────────────
    year = metadata.get("year")
    if year and era_prefs:
        decade = f"{(year // 10) * 10}s"
        total_era = sum(era_prefs.values())
        era_ratio = era_prefs.get(decade, 0) / total_era if total_era else 0
        scores.append((min(era_ratio * 3, 1.0), 0.2))  # scale up, cap at 1
    else:
        scores.append((0.5, 0.2))

    # Weighted sum
    total = sum(score * weight for score, weight in scores)
    total_weight = sum(weight for _, weight in scores)

    return total / total_weight if total_weight > 0 else 0.5
