"""Preference analysis — turns a raw anime list into a structured taste profile.

This is the "intelligence" layer between raw MAL data and the LLM.
The profile it produces will be fed to the recommendation engine in
Phase 3 as context, so the richer and more nuanced it is, the better
the recommendations will be.

Design decisions
────────────────
1. **Weighted affinity** — We don't just count how many anime of a
   genre a user watched.  We compute affinity as a combination of
   *frequency* (how many) and *satisfaction* (how they scored them).
   Someone who watched 50 action anime but scored them all 5/10
   doesn't actually like action.

2. **Unscored entries** — MAL score 0 means "not scored", not
   "terrible".  We exclude these from score averages but still count
   them for frequency (watching a lot of a genre even without scoring
   still signals interest).

3. **Era preference** — Grouping by decade reveals whether someone
   prefers classic or modern anime.  Surprisingly strong signal.

4. **Top 10** — The user's highest-rated shows are the single
   strongest signal for the LLM.  "Gave 10/10 to Steins;Gate,
   Monster, and Death Note" is more informative than any aggregate.

5. **Completion rate** — Do they finish what they start?  High
   completion rate → recommend confidently.  Low → maybe suggest
   shorter series or movies.
"""

from collections import defaultdict
from datetime import datetime, timezone

from app.models.anime import AnimeEntry


def analyze_preferences(entries: list[AnimeEntry]) -> dict:
    """Compute a full preference profile from a list of anime entries.

    Returns a dict matching the ``UserPreferenceProfile.profile_data``
    schema (see the model docstring for the full structure).

    This is a pure function — no DB access, no side effects.  Easy to
    test and reason about.
    """
    if not entries:
        return _empty_profile()

    # ── Basic stats ──────────────────────────────────────
    scored_entries = [e for e in entries if e.user_score > 0]
    completed = [e for e in entries if e.watch_status == "completed"]
    total_watched = len([e for e in entries if e.watch_status != "plan_to_watch"])

    mean_score = (
        sum(e.user_score for e in scored_entries) / len(scored_entries)
        if scored_entries
        else 0.0
    )

    # ── Score distribution ───────────────────────────────
    # How many anime did they give each score?  Tells us if they're
    # a generous scorer (lots of 8-10) or harsh (lots of 4-6).
    score_dist: dict[str, int] = defaultdict(int)
    for e in scored_entries:
        score_dist[str(e.user_score)] += 1

    # ── Genre / Theme / Studio affinity ──────────────────
    genre_affinity = _compute_affinity(entries, "genres")
    theme_affinity = _compute_affinity(entries, "themes")
    studio_affinity = _compute_affinity(entries, "studios")

    # ── Format preference ────────────────────────────────
    format_counts: dict[str, int] = defaultdict(int)
    for e in entries:
        if e.anime_type:
            format_counts[e.anime_type] += 1

    # ── Completion rate ──────────────────────────────────
    # Of anime they started (not plan_to_watch), how many did they finish?
    started = [e for e in entries if e.watch_status not in ("plan_to_watch",)]
    completion_rate = len(completed) / len(started) if started else 0.0

    # ── Top 10 ───────────────────────────────────────────
    # Highest-scored anime, breaking ties by MAL community score
    top_10 = sorted(
        scored_entries,
        key=lambda e: (e.user_score, e.mal_score or 0),
        reverse=True,
    )[:10]

    # ── Era preference ───────────────────────────────────
    era_counts: dict[str, int] = defaultdict(int)
    for e in entries:
        if e.year:
            decade = f"{(e.year // 10) * 10}s"
            era_counts[decade] += 1

    # ── Assemble profile ─────────────────────────────────
    return {
        "total_watched": total_watched,
        "total_scored": len(scored_entries),
        "mean_score": round(mean_score, 2),
        "score_distribution": dict(score_dist),
        "genre_affinity": genre_affinity,
        "theme_affinity": theme_affinity,
        "studio_affinity": studio_affinity,
        "preferred_formats": dict(format_counts),
        "completion_rate": round(completion_rate, 3),
        "top_10": [_entry_to_dict(e) for e in top_10],
        "watch_era_preference": dict(era_counts),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Affinity computation ─────────────────────────────────


def _compute_affinity(entries: list[AnimeEntry], field: str) -> list[dict]:
    """Compute affinity scores for a comma-separated metadata field.

    For each unique value (e.g. each genre), we calculate:
    - **count**: how many anime with this value the user watched
    - **avg_score**: their average score for anime with this value
      (only counting scored entries)
    - **affinity**: a normalised 0–1 score combining count and rating

    The affinity formula:
        affinity = 0.4 × normalised_count + 0.6 × normalised_score

    We weight score higher than count because *liking* a genre matters
    more than just *watching* a lot of it.  (Someone might watch tons
    of isekai because it's everywhere, but score them all 5/10.)
    """
    # Accumulate counts and scores per value
    counts: dict[str, int] = defaultdict(int)
    score_sums: dict[str, float] = defaultdict(float)
    score_counts: dict[str, int] = defaultdict(int)

    for entry in entries:
        raw_value = getattr(entry, field, None)
        if not raw_value:
            continue

        # Split comma-separated values: "Action, Adventure" → ["Action", "Adventure"]
        values = [v.strip() for v in raw_value.split(",") if v.strip()]

        for val in values:
            counts[val] += 1
            if entry.user_score > 0:
                score_sums[val] += entry.user_score
                score_counts[val] += 1

    if not counts:
        return []

    # Compute raw averages
    avg_scores: dict[str, float] = {}
    for val in counts:
        if score_counts[val] > 0:
            avg_scores[val] = score_sums[val] / score_counts[val]
        else:
            avg_scores[val] = 0.0

    # Normalise for affinity calculation
    max_count = max(counts.values()) if counts else 1
    max_score = 10.0  # MAL scores are 1-10

    results = []
    for val in counts:
        norm_count = counts[val] / max_count
        norm_score = avg_scores[val] / max_score

        # Weighted combination: score matters more than count
        affinity = 0.4 * norm_count + 0.6 * norm_score

        results.append({
            "genre": val,  # field name is "genre" in the schema for all types
            "count": counts[val],
            "avg_score": round(avg_scores[val], 2),
            "affinity": round(affinity, 3),
        })

    # Sort by affinity descending
    results.sort(key=lambda x: x["affinity"], reverse=True)
    return results


# ── Helpers ──────────────────────────────────────────────


def _entry_to_dict(entry: AnimeEntry) -> dict:
    """Convert an AnimeEntry to a dict suitable for the top_10 list."""
    return {
        "mal_anime_id": entry.mal_anime_id,
        "title": entry.title,
        "title_english": entry.title_english,
        "image_url": entry.image_url,
        "watch_status": entry.watch_status,
        "user_score": entry.user_score,
        "episodes_watched": entry.episodes_watched,
        "total_episodes": entry.total_episodes,
        "anime_type": entry.anime_type,
        "genres": entry.genres,
        "themes": entry.themes,
        "year": entry.year,
        "mal_score": entry.mal_score,
    }


def _empty_profile() -> dict:
    """Return a valid but empty preference profile."""
    return {
        "total_watched": 0,
        "total_scored": 0,
        "mean_score": 0.0,
        "score_distribution": {},
        "genre_affinity": [],
        "theme_affinity": [],
        "studio_affinity": [],
        "preferred_formats": {},
        "completion_rate": 0.0,
        "top_10": [],
        "watch_era_preference": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
