"""Taste Card service — computes a personality summary from a user's profile.

Built entirely from existing data:
  • UserPreferenceProfile.profile_data  (genre/theme/era signals)
  • AnimeEntry rows                     (dark-horse pick + contrarian trait)

No LLM call. Archetype = genre label + intensity modifier (categorical
match). Vibe = optional sub-label from theme affinity, adds nuance when
the genre label alone doesn't capture the user's specific flavour.

Caching
-------
Results are cached in-process for 1 hour per user_id.  Call
``invalidate_taste_card_cache(user_id)`` after a re-import to force a
fresh computation on the next request.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

# ── In-memory TTL cache ───────────────────────────────────────────────────────

_taste_card_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 3600  # 1 hour


def get_cached_taste_card(user_id: str) -> dict | None:
    if user_id in _taste_card_cache:
        ts, data = _taste_card_cache[user_id]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _taste_card_cache[user_id]
    return None


def set_cached_taste_card(user_id: str, data: dict) -> None:
    _taste_card_cache[user_id] = (time.time(), data)


def invalidate_taste_card_cache(user_id: str) -> None:
    _taste_card_cache.pop(user_id, None)


# ── Genre clusters ────────────────────────────────────────────────────────────
# Maps each genre label to the MAL genre/demographic names that belong to it.
# Checked against genre_affinity (except Mecha, which lives in theme_affinity).
#
# Demographics (Shounen, Shoujo, Seinen, Josei) are returned by Jikan as genres
# and accumulate affinity just like genre entries — they're included here so
# users whose lists skew heavily toward a demographic get an accurate label.

_GENRE_CLUSTER_MAP: dict[str, set[str]] = {
    "Sports":        {"Sports"},
    "Sci-Fi":        {"Sci-Fi"},
    "Boys Love":     {"Boys Love"},
    "Girls Love":    {"Girls Love"},
    # Shoujo and Josei tend to co-occur with romance/drama but signal a
    # distinct demographic lean worth surfacing on its own
    "Shoujo":        {"Shoujo", "Josei"},
    # Seinen is broad (action through slice-of-life) but mature-content
    # skewed — meaningful when it's the dominant signal
    "Seinen":        {"Seinen"},
    "Slice of Life": {"Slice of Life", "Iyashikei", "Gourmet"},
    "Comedy":        {"Comedy"},
    "Romance":       {"Romance"},
    "Drama":         {"Drama"},
    "Thriller":      {"Mystery", "Horror", "Thriller", "Suspense"},
    "Fantasy":       {"Fantasy", "Supernatural"},
    # Shounen absorbed into Action — they're nearly synonymous in practice
    "Action":        {"Action", "Adventure", "Shounen", "Martial Arts"},
}

_GENRE_MIN_AFFINITY = 0.55   # top cluster must clear this floor
_GENRE_MIN_GAP      = 0.12   # gap to second place must clear this
_MECHA_MIN_AFFINITY = 0.60   # Mecha (from themes) must beat top genre to override


# ── Intensity modifiers ───────────────────────────────────────────────────────
# Evaluated in priority order — first match wins.

def _match_intensity(profile_data: dict) -> str:
    total_watched: int     = profile_data.get("total_watched", 0)
    mean_score: float      = profile_data.get("mean_score", 0.0)
    completion_rate: float = profile_data.get("completion_rate", 0.0)
    era: dict[str, int]    = profile_data.get("watch_era_preference", {})
    peak_era = max(era, key=lambda k: era[k]) if era else ""

    if total_watched >= 300:
        return "Veteran"
    if mean_score > 0 and mean_score <= 6.2 and total_watched >= 100:
        return "Critic"
    if peak_era in ("1990s", "1980s", "1970s"):
        return "Classic"
    if completion_rate >= 0.90 and total_watched >= 50:
        return "Completionist"
    if mean_score >= 8.5 and total_watched >= 30:
        return "Enthusiast"
    if peak_era == "2020s" and total_watched >= 100:
        return "Seasonal"
    if completion_rate > 0 and completion_rate <= 0.35 and total_watched >= 20:
        return "Casual"
    return "Fan"


# ── Genre matching ────────────────────────────────────────────────────────────

def _match_genre(profile_data: dict) -> str:
    genre_affinity: list[dict] = profile_data.get("genre_affinity", [])[:10]
    theme_affinity: list[dict] = profile_data.get("theme_affinity", [])[:10]

    if not genre_affinity:
        return "Eclectic"

    theme_map    = {t["genre"]: t["affinity"] for t in theme_affinity}
    mecha_affinity = theme_map.get("Mecha", 0.0)

    top_affinity    = genre_affinity[0]["affinity"]
    second_affinity = genre_affinity[1]["affinity"] if len(genre_affinity) > 1 else 0.0
    top_genre       = genre_affinity[0]["genre"]

    # Mecha (theme) overrides if it's the strongest single signal
    if mecha_affinity >= _MECHA_MIN_AFFINITY and mecha_affinity > top_affinity:
        return "Mecha"

    # Eclectic: top signal too weak or no clear leader
    if top_affinity < _GENRE_MIN_AFFINITY:
        return "Eclectic"
    if top_affinity - second_affinity < _GENRE_MIN_GAP:
        return "Eclectic"

    for label, genre_set in _GENRE_CLUSTER_MAP.items():
        if top_genre in genre_set:
            return label

    return "Eclectic"


# ── Vibe clusters ─────────────────────────────────────────────────────────────
# Matched from theme_affinity. Sum of matching theme affinities must clear
# _VIBE_THRESHOLD for the vibe to be shown.

_VIBE_CLUSTERS: list[tuple[str, set[str]]] = [
    ("Isekai Escapist",    {"Isekai", "Reincarnation", "Game", "Parallel World"}),
    ("Dark & Gritty",      {"Psychological", "Gore", "Tragedy", "Survival"}),
    ("Cozy & Wholesome",   {"Iyashikei", "Cute Girls", "CGDCT", "Healing"}),
    ("Magical Girl",       {"Mahou Shoujo"}),
    ("Epic Battles",       {"Super Power", "Martial Arts", "Tournament", "Combat Sports"}),
    ("Military & War",     {"Military", "Historical", "War", "Samurai"}),
    ("School Life",        {"School", "Coming of Age", "Student Council"}),
    ("Sci-Fi & Mecha",     {"Mecha", "Space", "Cyberpunk"}),
    ("Mystery & Detective", {"Detective", "Crime", "Investigation"}),
    ("Romantic Drama",     {"Love Triangle", "Harem", "Reverse Harem", "Love Polygon"}),
    ("Music & Idols",      {"Music", "Idols (Female)", "Idols (Male)", "Performing Arts"}),
    ("Supernatural",       {"Vampire", "Demons", "Spirits", "Exorcism", "Paranormal", "Mythology"}),
]

_VIBE_THRESHOLD = 0.50

_VIBE_SKIP: dict[str, set[str]] = {
    "Sports":     {"Epic Battles"},          # already specific
    "Mecha":      {"Sci-Fi & Mecha"},        # echoes the label
    "Sci-Fi":     {"Sci-Fi & Mecha"},        # echoes the label
    "Thriller":   {"Mystery & Detective"},   # genre already covers this
    "Shoujo":     {"Magical Girl"},          # too expected to be informative
    "Boys Love":  {"Romantic Drama"},        # redundant
    "Girls Love": {"Romantic Drama"},        # redundant
}


def _match_vibe(profile_data: dict, genre_label: str) -> str | None:
    if genre_label in ("Sports", "Mecha"):
        return None

    theme_affinity: list[dict] = profile_data.get("theme_affinity", [])[:10]
    if not theme_affinity:
        return None

    theme_map  = {t["genre"]: t["affinity"] for t in theme_affinity}
    skip_vibes = _VIBE_SKIP.get(genre_label, set())

    cluster_scores: dict[str, float] = {}
    for vibe_name, theme_set in _VIBE_CLUSTERS:
        if vibe_name in skip_vibes:
            continue
        score = sum(theme_map.get(theme, 0.0) for theme in theme_set)
        if score > 0:
            cluster_scores[vibe_name] = score

    if not cluster_scores:
        return None

    best_vibe = max(cluster_scores, key=lambda k: cluster_scores[k])
    if cluster_scores[best_vibe] < _VIBE_THRESHOLD:
        return None

    return best_vibe


# ── Roasts ────────────────────────────────────────────────────────────────────

_GENRE_ROASTS: dict[str, str] = {
    "Action":        "If the first episode has no fight scene, the search continues.",
    "Romance":       "Emotionally compromised by people who refuse to have one conversation.",
    "Drama":         "Watches anime to feel things, then feels considerably too many things.",
    "Thriller":      "Picks the most distressing show available and calls it a relaxing evening.",
    "Fantasy":       "Requires at minimum one map, one prophecy, and one chosen one.",
    "Sci-Fi":        "Has opinions about fictional technology that would concern most engineers.",
    "Slice of Life": "Has cried at an anime about making tea. No regrets whatsoever.",
    "Comedy":        "Laughing alone at 2am, no context, no apologies.",
    "Sports":        "Convinced a training montage would fix most real-world problems.",
    "Mecha":         "Has strong feelings about fictional cockpit ergonomics.",
    "Shoujo":        "Trusts the magical girl to handle it. Always has, always will.",
    "Seinen":        "Picks the most thematically dense thing on the list every time.",
    "Boys Love":     "Has very specific opinions about which ships are canon and which are not.",
    "Girls Love":    "Has very specific opinions about which ships are canon and which are not.",
    "Eclectic":      "The recommendation algorithm has simply given up.",
}

_INTENSITY_OVERRIDES: dict[tuple[str, str], str] = {
    ("Action",        "Veteran"):       "Has watched every major shounen arc and is ready for more.",
    ("Action",        "Critic"):        "Watched a hundred fight scenes and found maybe three acceptable.",
    ("Fantasy",       "Veteran"):       "Could write a dissertation on isekai power escalation at this point.",
    ("Fantasy",       "Classic"):       "Watched fantasy before isekai was a genre and has opinions about it.",
    ("Romance",       "Critic"):        "Holds fictional couples to standards real people genuinely cannot meet.",
    ("Romance",       "Completionist"): "Cannot leave a love triangle unresolved. It is a medical condition.",
    ("Thriller",      "Critic"):        "Rates psychological horror a 6 and considers that a compliment.",
    ("Slice of Life", "Enthusiast"):    "Gave an anime about tea and coffee a perfect ten. Correct decision.",
    ("Drama",         "Critic"):        "The bar is high. The bar has never once been cleared.",
    ("Seinen",        "Veteran"):       "Has read every serious manga the anime didn't cover. Probably.",
    ("Eclectic",      "Veteran"):       "Has watched more anime than most people have watched anything, ever.",
    ("Sci-Fi",        "Classic"):       "Watched mecha before mecha was considered a genre. Respected.",
    ("Comedy",        "Veteran"):       "Has seen every gag anime twice and is still laughing.",
    ("Shoujo",        "Classic"):       "Has strong feelings about which magical girl era was the best.",
}


# ── Reasoning ────────────────────────────────────────────────────────────────

_GENRE_REASONING: dict[str, str] = {
    "Action":        "Action and adventure consistently score the highest on your list.",
    "Romance":       "Romance titles dominate your top scores and watch history.",
    "Drama":         "Drama is where you invest most of your attention and rating.",
    "Thriller":      "Mystery, horror, and thriller titles pull the highest ratings from you.",
    "Fantasy":       "Fantasy is your most-watched and highest-rated genre by a clear margin.",
    "Sci-Fi":        "Sci-fi titles sit at the top of both your watch history and your scores.",
    "Slice of Life": "Slice of life titles rate higher for you than almost anything else.",
    "Comedy":        "Comedy is your most-watched genre and rates well across the board.",
    "Sports":        "Sports anime consistently lands in your top-rated and most-watched titles.",
    "Mecha":         "Mecha is a defining thread through your list, scoring above your average.",
    "Shoujo":        "Shoujo and josei titles make up a dominant share of your highest-rated shows.",
    "Seinen":        "Seinen titles — mature, character-driven, often dense — are your most-scored.",
    "Boys Love":     "Boys love titles score consistently high across your list.",
    "Girls Love":    "Girls love titles score consistently high across your list.",
    "Eclectic":      "No single genre dominates — your list covers a wide range with no clear favourite.",
}

_INTENSITY_REASONING: dict[str, str] = {
    "Veteran":       "At {total_watched} shows in, you're one of the more committed watchers around.",
    "Critic":        "You score with a critical eye — {mean_score} average across {total_watched} shows tells the story.",
    "Classic":       "Your taste runs toward older series, with your heaviest watch history in the {peak_era}.",
    "Completionist": "You finish what you start — a {completion_rate}% completion rate puts you well above average.",
    "Enthusiast":    "You score generously, averaging {mean_score} out of 10 across your list.",
    "Seasonal":      "You stay current, tracking seasonal releases with {total_watched} shows under your belt.",
    "Casual":        "You cast a wide net — only {completion_rate}% completion, but the range is impressive.",
    "Fan":           "Your list of {total_watched} shows covers solid ground across the genre.",
}

_VIBE_REASONING: dict[str, str] = {
    "Isekai Escapist":     "Within fantasy, isekai and reincarnation stories pull you in more than anything else.",
    "Dark & Gritty":       "You gravitate toward the darker, more psychologically intense end of the spectrum.",
    "Cozy & Wholesome":    "Your top themes lean cosy — healing, slice-of-life calm, low-stakes comfort watches.",
    "Magical Girl":        "Magical girl shows are a consistent high point across your scores.",
    "Epic Battles":        "Super power and tournament arcs are a recurring theme in your favourites.",
    "Military & War":      "Military and historical settings show up consistently across your highest-rated titles.",
    "School Life":         "School settings and coming-of-age stories run throughout your watch history.",
    "Sci-Fi & Mecha":      "Mecha and space settings are the specific corner of sci-fi you return to most.",
    "Mystery & Detective": "Detective and crime storylines appear regularly in your top-rated picks.",
    "Romantic Drama":      "Love triangles and emotionally complex relationship dynamics dominate your picks.",
    "Music & Idols":       "Music, idol, and performance shows appear consistently in your highest-rated titles.",
    "Supernatural":        "Supernatural elements — demons, spirits, vampires — thread through your favourites.",
}


def _compute_reasoning(
    profile_data: dict,
    genre_label: str,
    intensity: str,
    vibe: str | None,
) -> str:
    total_watched: int     = profile_data.get("total_watched", 0)
    mean_score: float      = profile_data.get("mean_score", 0.0)
    completion_rate: float = profile_data.get("completion_rate", 0.0)
    era: dict[str, int]    = profile_data.get("watch_era_preference", {})
    peak_era = max(era, key=lambda k: era[k]) if era else "that era"

    genre_sentence = _GENRE_REASONING.get(genre_label, "")

    intensity_template = _INTENSITY_REASONING.get(intensity, "")
    intensity_sentence = intensity_template.format(
        total_watched=total_watched,
        mean_score=f"{mean_score:.1f}",
        completion_rate=f"{completion_rate * 100:.0f}",
        peak_era=peak_era,
    )

    vibe_sentence = _VIBE_REASONING.get(vibe, "") if vibe else ""

    parts = [s for s in [genre_sentence, intensity_sentence, vibe_sentence] if s]
    return " ".join(parts)


def _get_roast(genre_label: str, intensity: str) -> str:
    return _INTENSITY_OVERRIDES.get(
        (genre_label, intensity),
        _GENRE_ROASTS.get(genre_label, "Taste is certainly a thing they have."),
    )


# ── Sub-computations ──────────────────────────────────────────────────────────

def compute_top_genres(profile_data: dict) -> list[str]:
    genre_affinity: list[dict] = profile_data.get("genre_affinity", [])
    return [g["genre"] for g in genre_affinity[:5]]


def compute_favorite_era(profile_data: dict) -> str:
    era: dict[str, int] = profile_data.get("watch_era_preference", {})
    if not era:
        return "Unknown"
    return max(era, key=lambda k: era[k])


def compute_dark_horse(entries: list) -> dict | None:
    """Find the most contrarian pick: completed, user rated it ≥7, and
    the user's score beats the community score by at least 1.5 points.

    Sorting: largest gap first, then highest user score as tiebreaker.
    """
    candidates = [
        e for e in entries
        if (
            e.user_score is not None
            and e.user_score >= 7
            and e.mal_score is not None
            and e.mal_score > 0
            and (e.user_score - e.mal_score) >= 1.5
            and e.watch_status == "completed"
        )
    ]
    if not candidates:
        return None

    candidates.sort(
        key=lambda e: (e.user_score - e.mal_score, e.user_score),
        reverse=True,
    )
    pick = candidates[0]
    return {
        "mal_anime_id": pick.mal_anime_id,
        "title":        pick.title,
        "image_url":    pick.image_url,
        "user_score":   pick.user_score,
        "mal_score":    pick.mal_score,
        "genres":       pick.genres,
    }


def compute_taste_traits(profile_data: dict, entries: list) -> list[str]:
    """Derive up to 5 personality chips from rule-based conditions.

    Rules are checked in priority order; the first 5 that fire are returned.
    Genre-based traits are omitted here — the archetype already surfaces
    genre identity; traits focus on behaviour, format, and scoring patterns.
    """
    mean_score: float          = profile_data.get("mean_score", 0.0)
    completion_rate: float     = profile_data.get("completion_rate", 0.0)
    total_watched: int         = profile_data.get("total_watched", 0)
    genre_affinity: list[dict] = profile_data.get("genre_affinity", [])
    theme_affinity: list[dict] = profile_data.get("theme_affinity", [])
    studio_affinity: list[dict] = profile_data.get("studio_affinity", [])
    preferred_formats: dict    = profile_data.get("preferred_formats", {})
    score_dist: dict           = profile_data.get("score_distribution", {})
    era: dict[str, int]        = profile_data.get("watch_era_preference", {})
    peak_era = max(era, key=lambda k: era[k]) if era else ""

    # --- derived signals ---

    # Score spreader: uses 6+ distinct score values with at least 1 entry each
    distinct_scores_used = sum(1 for v in score_dist.values() if v > 0)

    # Genre purist: dominant genre has a large lead over second
    genre_gap = (
        genre_affinity[0]["affinity"] - genre_affinity[1]["affinity"]
        if len(genre_affinity) >= 2 else 0.0
    )

    # Thematic obsessive: top theme affinity is very high
    top_theme_affinity = theme_affinity[0]["affinity"] if theme_affinity else 0.0

    # Studio loyalist: top studio has 5+ anime on the list
    top_studio_count = studio_affinity[0]["count"] if studio_affinity else 0

    # Movie buff: ≥20% of list is Movies
    movie_count = preferred_formats.get("Movie", 0)
    movie_ratio = movie_count / total_watched if total_watched > 0 else 0.0

    # Contrarian: 10+ completed entries where user score beats community by ≥2
    contrarian_count = sum(
        1 for e in entries
        if (
            e.user_score is not None
            and e.user_score >= 6
            and e.mal_score is not None
            and e.mal_score > 0
            and (e.user_score - e.mal_score) >= 2.0
            and e.watch_status == "completed"
        )
    )

    rules: list[tuple[bool, str]] = [
        # Volume
        (total_watched >= 300,                      "Anime Veteran"),
        (0 < total_watched < 30,                    "Getting Started"),
        # Scoring behaviour
        (mean_score >= 8.0,                         "Generous Scorer"),
        (mean_score > 0 and mean_score <= 5.5,      "Harsh Critic"),
        (distinct_scores_used >= 6,                 "Score Spreader"),
        (contrarian_count >= 10,                    "Contrarian"),
        # Completion behaviour
        (completion_rate >= 0.90 and total_watched >= 50, "Completionist"),
        (completion_rate > 0 and completion_rate <= 0.35 and total_watched >= 20, "Serial Dropper"),
        # Era
        (peak_era in ("1990s", "1980s", "1970s"),   "Vintage Collector"),
        (peak_era == "2020s" and total_watched >= 50, "Seasonal Surfer"),
        # Format
        (movie_ratio >= 0.20,                       "Movie Buff"),
        # Taste shape
        (genre_gap >= 0.30,                         "Genre Purist"),
        (top_theme_affinity >= 0.85,                "Thematic Obsessive"),
        (top_studio_count >= 5,                     "Studio Loyalist"),
    ]

    traits: list[str] = []
    for condition, label in rules:
        if condition:
            traits.append(label)
        if len(traits) == 5:
            break
    return traits


# ── Main orchestrator ─────────────────────────────────────────────────────────

def compute_taste_card(profile_data: dict, entries: list) -> dict:
    """Build the full taste card dict from profile data and anime entries."""
    genre_label = _match_genre(profile_data)
    intensity   = _match_intensity(profile_data)
    vibe        = _match_vibe(profile_data, genre_label)
    archetype   = f"{genre_label} {intensity}"
    roast       = _get_roast(genre_label, intensity)
    reasoning   = _compute_reasoning(profile_data, genre_label, intensity, vibe)

    return {
        "archetype":    archetype,
        "roast":        roast,
        "vibe":         vibe,
        "reasoning":    reasoning,
        "top_genres":   compute_top_genres(profile_data),
        "favorite_era": compute_favorite_era(profile_data),
        "dark_horse":   compute_dark_horse(entries),
        "taste_traits": compute_taste_traits(profile_data, entries),
        "entry_count":  profile_data.get("total_watched", 0),
        "avg_score":    round(profile_data.get("mean_score", 0.0), 1),
        "generated_at": datetime.now(UTC).isoformat(),
    }
