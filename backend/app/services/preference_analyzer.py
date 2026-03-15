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

Phase 3.5 additions
───────────────────
6. **Feedback adjustments** — ``apply_feedback_adjustments()`` takes
   the base profile and a list of ``RecommendationFeedback`` records,
   then adjusts genre/theme affinities based on user reactions:
   - "liked" → boost genres/themes by +0.05
   - "disliked" → reduce genres/themes by -0.03
   The asymmetry is intentional: positive signals are stronger than
   negative ones (disliking one romance anime doesn't mean you hate
   all romance).  Adjustments are capped at [0.0, 1.0] to prevent
   runaway feedback loops.
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


# ═════════════════════════════════════════════════════════
# Phase 3.5 — Feedback-driven preference tuning
# ═════════════════════════════════════════════════════════
#
# This is the "learning" part of the recommendation engine.
# Without it, every "Generate" call starts from the same base
# profile.  With it, the system remembers: "you liked dark
# thrillers and disliked romance comedies" and adjusts future
# recommendations accordingly.
#
# How it works:
# 1. Start with the base profile (computed from MAL list)
# 2. For each "liked" feedback, boost the genres/themes of
#    that anime by a small amount (+0.05)
# 3. For each "disliked" feedback, reduce the genres/themes
#    by a smaller amount (-0.03)
# 4. Return the adjusted profile
#
# Why asymmetric adjustments?
# ───────────────────────────
# Positive signals are more reliable than negative ones.
# If someone clicks 👍 on a dark thriller, they're actively
# endorsing that genre.  But clicking 👎 on ONE romance anime
# doesn't mean they hate ALL romance — maybe that specific
# show just didn't appeal.  So we boost more than we penalise.
#
# Why small increments?
# ─────────────────────
# Large adjustments cause "filter bubbles" — the system only
# recommends what you already like, creating an echo chamber.
# Small increments (0.05, 0.03) mean it takes ~10 likes to
# significantly shift a genre's affinity.  This is gradual
# enough to avoid runaway feedback loops while still being
# responsive to user preferences.
#
# Why cap at [0.0, 1.0]?
# ──────────────────────
# Affinity scores are normalised to 0–1.  Without capping,
# repeated likes could push a genre to 1.5 or higher, which
# would dominate the re-ranking formula unfairly.  Capping
# ensures all genres compete on a level playing field.

# Tuning constants — adjust these to change feedback sensitivity
LIKED_BOOST = 0.05    # how much to boost per "liked" feedback
DISLIKED_PENALTY = 0.03  # how much to reduce per "disliked" feedback
MIN_AFFINITY = 0.0    # floor for affinity scores
MAX_AFFINITY = 1.0    # ceiling for affinity scores


def apply_feedback_adjustments(
    base_profile: dict,
    feedbacks: list,
) -> dict:
    """Apply feedback-based adjustments to a preference profile.

    Takes the base profile (computed from the user's MAL list) and
    a list of ``RecommendationFeedback`` records, then returns a
    new profile with adjusted genre/theme affinities.

    This is a pure function — it doesn't modify the base profile
    or the feedback records.  It returns a new dict.

    Args:
        base_profile: The user's computed preference profile dict
            (from ``UserPreferenceProfile.profile_data``).
        feedbacks: List of ``RecommendationFeedback`` ORM objects
            (or any objects with ``feedback_type``, ``genres``, and
            ``themes`` attributes).

    Returns:
        A new profile dict with adjusted affinities.  If there are
        no feedbacks, returns the base profile unchanged.

    Example:
        If the user liked an anime with genres "Action, Thriller"
        and disliked one with "Romance, Comedy":

        Before: Action affinity = 0.70, Romance affinity = 0.45
        After:  Action affinity = 0.75, Romance affinity = 0.42
    """
    if not feedbacks:
        return base_profile

    # Deep copy the profile so we don't mutate the original.
    # We only need to copy the affinity lists since those are
    # the only parts we modify.
    import copy
    adjusted = copy.deepcopy(base_profile)

    # Compute adjustments: {genre_name: total_delta}
    genre_deltas: dict[str, float] = defaultdict(float)
    theme_deltas: dict[str, float] = defaultdict(float)

    for fb in feedbacks:
        feedback_type = fb.feedback_type if hasattr(fb, "feedback_type") else fb.get("feedback_type", "")
        genres_str = fb.genres if hasattr(fb, "genres") else fb.get("genres", "")
        themes_str = fb.themes if hasattr(fb, "themes") else fb.get("themes", "")

        if feedback_type == "liked":
            delta = LIKED_BOOST
        elif feedback_type == "disliked":
            delta = -DISLIKED_PENALTY
        else:
            # "watched" feedback doesn't affect affinities —
            # it only affects the exclusion set (handled in the API layer)
            continue

        # Apply delta to each genre of this anime
        if genres_str:
            for genre in genres_str.split(","):
                genre = genre.strip()
                if genre:
                    genre_deltas[genre] += delta

        # Apply delta to each theme of this anime
        if themes_str:
            for theme in themes_str.split(","):
                theme = theme.strip()
                if theme:
                    theme_deltas[theme] += delta

    # Apply genre adjustments
    adjusted["genre_affinity"] = _apply_deltas(
        adjusted.get("genre_affinity", []),
        genre_deltas,
    )

    # Apply theme adjustments
    adjusted["theme_affinity"] = _apply_deltas(
        adjusted.get("theme_affinity", []),
        theme_deltas,
    )

    return adjusted


def _apply_deltas(
    affinity_list: list[dict],
    deltas: dict[str, float],
) -> list[dict]:
    """Apply accumulated deltas to an affinity list.

    For each entry in the affinity list, if there's a delta for
    that genre/theme, add it to the affinity score (clamped to
    [MIN_AFFINITY, MAX_AFFINITY]).

    If a delta exists for a genre/theme NOT in the list (e.g.,
    the user liked an anime with a genre they haven't watched
    much of), we add a new entry with a base affinity of 0.3
    plus the delta.  This lets feedback introduce new genres
    into the profile.

    Args:
        affinity_list: List of affinity dicts (each has "genre",
            "count", "avg_score", "affinity" keys).
        deltas: {name: total_delta} mapping.

    Returns:
        New affinity list with adjustments applied, re-sorted
        by affinity descending.
    """
    if not deltas:
        return affinity_list

    # Build a lookup for existing entries
    existing: dict[str, dict] = {}
    result: list[dict] = []

    for entry in affinity_list:
        name = entry.get("genre", "")
        # Copy the entry so we don't mutate the original
        new_entry = dict(entry)

        if name in deltas:
            new_affinity = new_entry["affinity"] + deltas[name]
            new_entry["affinity"] = round(
                max(MIN_AFFINITY, min(MAX_AFFINITY, new_affinity)), 3
            )

        existing[name] = new_entry
        result.append(new_entry)

    # Add new entries for genres/themes not already in the list
    for name, delta in deltas.items():
        if name not in existing:
            # Base affinity of 0.3 for newly discovered genres
            # (not 0.0, because the user showed interest via feedback)
            new_affinity = max(MIN_AFFINITY, min(MAX_AFFINITY, 0.3 + delta))
            result.append({
                "genre": name,
                "count": 0,  # not from their watch history
                "avg_score": 0.0,
                "affinity": round(new_affinity, 3),
            })

    # Re-sort by affinity descending
    result.sort(key=lambda x: x["affinity"], reverse=True)
    return result
