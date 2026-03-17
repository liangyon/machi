"""CLI commands for Machi backend operations.

This module provides command-line tools for operations that are too
long-running or infrastructure-level for API endpoints:

• ``ingest-anime`` — Populate the anime knowledge base from Jikan API
  and embed into the vector store.

Usage:
    # From the backend directory:
    uv run python -m app.cli ingest-anime --pages 10
    uv run python -m app.cli ingest-anime --all              # Fetch ENTIRE MAL catalog (~27k anime)
    uv run python -m app.cli ingest-anime --all --skip-embed # Fetch all, embed later
    uv run python -m app.cli ingest-anime --pages 2 --skip-embed  # DB only, no vectors
    uv run python -m app.cli embed                           # Embed un-embedded entries
    uv run python -m app.cli stats                           # Show catalog stats

    # Or via Makefile:
    make ingest-anime           # Default: 250 top + 4 seasons
    make ingest-anime-all       # Full catalog (~27k anime, one-time)
    make ingest-anime-small     # Quick test with 50 anime

Why a CLI script instead of an API endpoint?
────────────────────────────────────────────
• Ingesting thousands of anime takes minutes (rate-limited API calls)
• It's an admin/setup operation, not user-triggered
• CLI gives real-time progress output in the terminal
• Easy to run in CI/CD or as a scheduled job later
"""

from __future__ import annotations

import asyncio
import argparse
import sys
import time


def main():
    """Entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Machi CLI — anime knowledge base management",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── ingest-anime command ─────────────────────────────
    ingest_parser = subparsers.add_parser(
        "ingest-anime",
        help="Fetch anime from Jikan API and populate the knowledge base",
    )
    ingest_parser.add_argument(
        "--pages",
        type=int,
        default=10,
        help="Pages of top anime to fetch (25 per page, default: 10 = 250 anime)",
    )
    ingest_parser.add_argument(
        "--seasons",
        type=int,
        default=4,
        help="Number of recent seasons to fetch (default: 4 = 1 year)",
    )
    ingest_parser.add_argument(
        "--skip-embed",
        action="store_true",
        help="Only populate the DB, skip vector store embedding",
    )
    ingest_parser.add_argument(
        "--embed-only",
        action="store_true",
        help="Only embed existing DB entries into vector store (no API fetching)",
    )
    ingest_parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Fetch the ENTIRE MAL anime catalog (~27,000 anime). "
            "Crawls all pages of /top/anime until exhausted. "
            "One-time operation: takes ~10-15 min for fetching, "
            "plus ~5 min for embedding (~$0.50-1.00 OpenAI cost). "
            "Overrides --pages and --seasons."
        ),
    )

    # ── stats command ────────────────────────────────────
    subparsers.add_parser(
        "stats",
        help="Show catalog and vector store statistics",
    )

    # ── embed command ────────────────────────────────────
    subparsers.add_parser(
        "embed",
        help="Embed all un-embedded catalog entries into the vector store",
    )

    # ── seed-demo command ────────────────────────────────
    subparsers.add_parser(
        "seed-demo",
        help="Seed a demo user with curated MAL data and pre-generated recommendations",
    )

    args = parser.parse_args()

    if args.command == "ingest-anime":
        asyncio.run(cmd_ingest_anime(args))
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "embed":
        cmd_embed()
    elif args.command == "seed-demo":
        cmd_seed_demo()
    else:
        parser.print_help()
        sys.exit(1)


# ═════════════════════════════════════════════════════════
# ingest-anime — the main ingestion pipeline
# ═════════════════════════════════════════════════════════


async def cmd_ingest_anime(args):
    """Fetch anime from Jikan and populate the knowledge base.

    This is the full pipeline:
    1. Fetch top anime from Jikan (paginated)
    2. Fetch recent seasonal anime
    3. Parse all responses into our catalog format
    4. Upsert into the AnimeCatalogEntry table
    5. Embed new entries into the vector store

    Each step prints progress so you can watch it work.
    """
    from app.services.anime_catalog import (
        fetch_top_anime,
        fetch_seasonal_anime,
        parse_jikan_to_catalog,
        upsert_catalog_entries,
    )
    from app.db.session import SessionLocal

    start_time = time.time()

    if args.embed_only:
        print("📦 Embed-only mode: skipping API fetching")
        _embed_unembedded_entries()
        return

    # ── Handle --all mode ────────────────────────────────
    # --all overrides --pages and --seasons.  It crawls the entire
    # /top/anime endpoint until Jikan returns no more results.
    # Jikan's /top/anime is sorted by score and includes EVERY
    # anime on MAL (~27,000+), so we don't need seasonal fetching.
    if getattr(args, "all", False):
        pages = 1200  # ~30,000 / 25 per page — more than enough
        seasons = 0   # not needed, top anime covers everything
        print("\n🌐 FULL CATALOG MODE — fetching ALL anime from MAL")
        print("   This is a one-time operation. Expect ~10-15 minutes.\n")
    else:
        pages = args.pages
        seasons = args.seasons

    # ── Step 1: Fetch top anime ──────────────────────────
    if getattr(args, "all", False):
        print(f"🔍 Fetching ALL anime (crawling /top/anime until exhausted)...")
    else:
        print(f"🔍 Fetching top anime ({pages} pages × 25 = up to {pages * 25} anime)...")

    def on_page(page, total):
        if getattr(args, "all", False):
            # For --all mode, show progress every 10 pages to reduce noise
            if page % 10 == 0 or page <= 3:
                elapsed_so_far = time.time() - start_time
                rate = total / elapsed_so_far if elapsed_so_far > 0 else 0
                print(f"   Page {page} — {total} anime fetched ({rate:.0f} anime/s)")
        else:
            print(f"   Page {page}/{pages} — {total} anime so far")

    raw_top = await fetch_top_anime(pages=pages, on_page=on_page)
    print(f"   ✅ Got {len(raw_top)} top anime\n")

    # ── Step 2: Fetch recent seasons ─────────────────────
    raw_seasonal: list[dict] = []
    if seasons > 0:
        print(f"🗓️  Fetching {seasons} recent seasons...")
        seasons_list = _get_recent_seasons(seasons)

        for year, season in seasons_list:
            print(f"   Fetching {season.capitalize()} {year}...")
            seasonal = await fetch_seasonal_anime(year, season, pages=3)
            raw_seasonal.extend(seasonal)
            print(f"   Got {len(seasonal)} anime from {season.capitalize()} {year}")

        print(f"   ✅ Got {len(raw_seasonal)} seasonal anime total\n")

    # ── Step 3: Parse all entries ────────────────────────
    print("📝 Parsing anime metadata...")

    all_parsed: list[dict] = []

    # Parse top anime
    for i, raw in enumerate(raw_top):
        page_num = (i // 25) + 1
        parsed = parse_jikan_to_catalog(raw, source=f"top_anime_page_{page_num}")
        if parsed.get("mal_id"):
            all_parsed.append(parsed)

    # Parse seasonal anime
    for raw in raw_seasonal:
        parsed = parse_jikan_to_catalog(raw, source="seasonal")
        if parsed.get("mal_id"):
            all_parsed.append(parsed)

    print(f"   ✅ Parsed {len(all_parsed)} anime entries\n")

    # ── Step 4: Upsert into database ─────────────────────
    # For large batches, upsert in chunks to avoid holding a huge
    # transaction and to show progress.
    print("💾 Saving to database (upserting by MAL ID)...")
    db = SessionLocal()
    try:
        if len(all_parsed) > 1000:
            # Chunk large batches for progress reporting
            stats = {"inserted": 0, "updated": 0, "skipped": 0}
            chunk_size = 500
            for i in range(0, len(all_parsed), chunk_size):
                chunk = all_parsed[i : i + chunk_size]
                chunk_stats = upsert_catalog_entries(db, chunk)
                stats["inserted"] += chunk_stats["inserted"]
                stats["updated"] += chunk_stats["updated"]
                stats["skipped"] += chunk_stats["skipped"]
                total_done = min(i + chunk_size, len(all_parsed))
                print(
                    f"   Progress: {total_done}/{len(all_parsed)} "
                    f"(+{chunk_stats['inserted']} new, +{chunk_stats['updated']} updated)"
                )
        else:
            stats = upsert_catalog_entries(db, all_parsed)

        print(f"   ✅ Inserted: {stats['inserted']}, Updated: {stats['updated']}, Skipped: {stats['skipped']}\n")
    finally:
        db.close()

    # ── Step 5: Embed into vector store ──────────────────
    if not args.skip_embed:
        _embed_unembedded_entries()
    else:
        print("⏭️  Skipping vector store embedding (--skip-embed)")

    # ── Summary ──────────────────────────────────────────
    elapsed = time.time() - start_time
    print(f"\n🎉 Done! Total time: {elapsed:.1f}s")
    print(f"   Fetched: {len(raw_top) + len(raw_seasonal)} anime from Jikan")
    print(f"   Catalog: {stats['inserted']} new, {stats['updated']} updated")


def _embed_unembedded_entries():
    """Embed all catalog entries that haven't been embedded yet.

    Reads from the AnimeCatalogEntry table, filters for
    ``is_embedded=False``, and pushes them to the vector store.
    Then marks them as embedded in the DB.
    """
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.anime import AnimeCatalogEntry
    from app.services.vector_store import add_anime_to_store

    db = SessionLocal()
    try:
        # Find un-embedded entries
        entries = (
            db.execute(
                select(AnimeCatalogEntry).where(
                    AnimeCatalogEntry.is_embedded == False,  # noqa: E712
                    AnimeCatalogEntry.embedding_text.isnot(None),
                )
            )
            .scalars()
            .all()
        )

        if not entries:
            print("✅ All catalog entries are already embedded!")
            return

        print(f"🧠 Embedding {len(entries)} anime into vector store...")

        # Convert ORM objects to dicts for the vector store
        entry_dicts = [
            {
                "mal_id": e.mal_id,
                "title": e.title,
                "image_url": e.image_url,
                "embedding_text": e.embedding_text,
                "genres": e.genres,
                "themes": e.themes,
                "anime_type": e.anime_type,
                "year": e.year,
                "mal_score": e.mal_score,
                "mal_members": e.mal_members,
            }
            for e in entries
        ]

        added = add_anime_to_store(entry_dicts)
        print(f"   ✅ Embedded {added} anime into vector store")

        # Mark as embedded in the DB
        for entry in entries:
            entry.is_embedded = True
        db.commit()
        print(f"   ✅ Marked {len(entries)} entries as embedded in DB")

    finally:
        db.close()


# ═════════════════════════════════════════════════════════
# stats — show catalog and vector store statistics
# ═════════════════════════════════════════════════════════


def cmd_stats():
    """Show statistics about the anime catalog and vector store."""
    from sqlalchemy import select, func
    from app.db.session import SessionLocal
    from app.models.anime import AnimeCatalogEntry

    db = SessionLocal()
    try:
        # Catalog stats
        total = db.execute(
            select(func.count(AnimeCatalogEntry.id))
        ).scalar() or 0

        embedded = db.execute(
            select(func.count(AnimeCatalogEntry.id)).where(
                AnimeCatalogEntry.is_embedded == True  # noqa: E712
            )
        ).scalar() or 0

        not_embedded = total - embedded

        print("\n📊 Anime Catalog Statistics")
        print(f"   Total entries:     {total}")
        print(f"   Embedded:          {embedded}")
        print(f"   Not yet embedded:  {not_embedded}")

        # Source breakdown
        sources = db.execute(
            select(
                AnimeCatalogEntry.source,
                func.count(AnimeCatalogEntry.id),
            ).group_by(AnimeCatalogEntry.source)
        ).all()

        if sources:
            print("\n   Sources:")
            for source, count in sources:
                print(f"     {source or 'unknown'}: {count}")

    finally:
        db.close()

    # Vector store stats (only if OPENAI_API_KEY is set)
    try:
        from app.services.vector_store import get_store_stats
        vs_stats = get_store_stats()
        print(f"\n🧠 Vector Store Statistics")
        print(f"   Documents:   {vs_stats['total_documents']}")
        print(f"   Collection:  {vs_stats['collection_name']}")
        print(f"   Directory:   {vs_stats['persist_directory']}")
    except RuntimeError as e:
        print(f"\n⚠️  Vector store not available: {e}")

    print()


# ═════════════════════════════════════════════════════════
# embed — embed un-embedded entries
# ═════════════════════════════════════════════════════════


def cmd_embed():
    """Embed all un-embedded catalog entries into the vector store."""
    _embed_unembedded_entries()


# ═════════════════════════════════════════════════════════
# seed-demo — create demo user with curated data
# ═════════════════════════════════════════════════════════


DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
DEMO_SESSION_ID = "00000000-0000-0000-0000-000000000002"
DEMO_LIST_ID = "00000000-0000-0000-0000-000000000003"


def cmd_seed_demo():
    """Seed a demo user with curated anime list, preference profile,
    and pre-generated recommendations.

    This creates everything needed for the landing page demo:
    1. A demo user account (demo@machi.app)
    2. A curated MAL import (~70 anime, diverse taste)
    3. A computed preference profile (no OpenAI call needed)
    4. Pre-generated recommendations with AI reasoning (hardcoded)

    Idempotent: running multiple times updates existing data.
    Zero external API cost — all data comes from the fixture file.
    """
    import json
    from pathlib import Path
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.user import User
    from app.models.anime import AnimeList, AnimeEntry, UserPreferenceProfile
    from app.models.recommendation import RecommendationSession, RecommendationEntry
    from app.services.auth import hash_password
    from app.services.preference_analyzer import analyze_preferences

    # ── Load fixture data ────────────────────────────────
    fixture_path = Path(__file__).parent / "fixtures" / "demo_seed.json"
    with open(fixture_path) as f:
        fixture = json.load(f)

    demo_cfg = fixture["demo_user"]
    mal_username = fixture["mal_username"]
    anime_entries_data = fixture["anime_entries"]
    recommendations_data = fixture["recommendations"]

    db = SessionLocal()
    try:
        # ── Step 1: Create or update demo user ───────────
        print("👤 Creating demo user...")
        existing_user = db.execute(
            select(User).where(User.email == demo_cfg["email"])
        ).scalar_one_or_none()

        if existing_user:
            user = existing_user
            user.name = demo_cfg["name"]
            user.hashed_password = hash_password(demo_cfg["password"])
            print(f"   Updated existing user: {user.email} (id={user.id})")
        else:
            user = User(
                id=DEMO_USER_ID,
                email=demo_cfg["email"],
                name=demo_cfg["name"],
                provider=demo_cfg["provider"],
                hashed_password=hash_password(demo_cfg["password"]),
                is_verified=True,
            )
            db.add(user)
            db.flush()
            print(f"   Created user: {user.email} (id={user.id})")

        user_id = user.id

        # ── Step 2: Create anime list + entries ──────────
        print(f"📋 Importing {len(anime_entries_data)} anime entries...")
        existing_list = db.execute(
            select(AnimeList).where(AnimeList.user_id == user_id)
        ).scalar_one_or_none()

        if existing_list:
            # Delete old entries for clean re-seed
            for entry in existing_list.entries:
                db.delete(entry)
            db.flush()
            anime_list = existing_list
            anime_list.mal_username = mal_username
            anime_list.sync_status = "completed"
        else:
            anime_list = AnimeList(
                id=DEMO_LIST_ID,
                user_id=user_id,
                mal_username=mal_username,
                sync_status="completed",
            )
            db.add(anime_list)
            db.flush()

        # Add entries
        orm_entries = []
        for entry_data in anime_entries_data:
            entry = AnimeEntry(
                anime_list_id=anime_list.id,
                mal_anime_id=entry_data["mal_anime_id"],
                title=entry_data["title"],
                title_english=entry_data.get("title_english"),
                image_url=entry_data.get("image_url"),
                watch_status=entry_data["watch_status"],
                user_score=entry_data.get("user_score", 0),
                episodes_watched=entry_data.get("episodes_watched", 0),
                total_episodes=entry_data.get("total_episodes"),
                anime_type=entry_data.get("anime_type"),
                genres=entry_data.get("genres"),
                themes=entry_data.get("themes"),
                studios=entry_data.get("studios"),
                year=entry_data.get("year"),
                mal_score=entry_data.get("mal_score"),
            )
            db.add(entry)
            orm_entries.append(entry)

        anime_list.total_entries = len(orm_entries)
        anime_list.last_synced_at = datetime.now(timezone.utc)
        db.flush()
        print(f"   Added {len(orm_entries)} entries to anime list")

        # ── Step 3: Compute preference profile ───────────
        print("🧠 Computing preference profile...")
        profile_data = analyze_preferences(orm_entries)

        existing_profile = db.execute(
            select(UserPreferenceProfile).where(
                UserPreferenceProfile.user_id == user_id
            )
        ).scalar_one_or_none()

        if existing_profile:
            existing_profile.profile_data = profile_data
            existing_profile.anime_count = len(orm_entries)
            existing_profile.generated_at = datetime.now(timezone.utc)
            print("   Updated existing preference profile")
        else:
            profile = UserPreferenceProfile(
                user_id=user_id,
                profile_data=profile_data,
                anime_count=len(orm_entries),
                generated_at=datetime.now(timezone.utc),
            )
            db.add(profile)
            print("   Created preference profile")

        # ── Step 4: Create recommendation session ────────
        print(f"🎯 Seeding {len(recommendations_data)} pre-generated recommendations...")

        # Delete existing demo sessions
        existing_sessions = db.execute(
            select(RecommendationSession).where(
                RecommendationSession.user_id == user_id
            )
        ).scalars().all()
        for session in existing_sessions:
            db.delete(session)
        db.flush()

        session = RecommendationSession(
            id=DEMO_SESSION_ID,
            user_id=user_id,
            custom_query=None,
            used_fallback=False,
            total_count=len(recommendations_data),
            generated_at=datetime.now(timezone.utc),
        )
        db.add(session)
        db.flush()

        for rec_data in recommendations_data:
            rec_entry = RecommendationEntry(
                session_id=session.id,
                mal_id=rec_data["mal_id"],
                title=rec_data["title"],
                image_url=rec_data.get("image_url"),
                genres=rec_data.get("genres", ""),
                themes=rec_data.get("themes", ""),
                synopsis=rec_data.get("synopsis", ""),
                mal_score=rec_data.get("mal_score"),
                year=rec_data.get("year"),
                anime_type=rec_data.get("anime_type"),
                reasoning=rec_data.get("reasoning", ""),
                confidence=rec_data.get("confidence", "medium"),
                similar_to=rec_data.get("similar_to", []),
                similarity_score=rec_data.get("similarity_score", 0.0),
                preference_score=rec_data.get("preference_score", 0.0),
                combined_score=rec_data.get("combined_score", 0.0),
                is_fallback=rec_data.get("is_fallback", False),
            )
            db.add(rec_entry)

        db.commit()
        print(f"   Created recommendation session with {len(recommendations_data)} entries")

        # ── Summary ──────────────────────────────────────
        print(f"\n🎉 Demo seed complete!")
        print(f"   User:             {demo_cfg['email']} / {demo_cfg['password']}")
        print(f"   Anime entries:    {len(orm_entries)}")
        print(f"   Recommendations:  {len(recommendations_data)}")
        print(f"   User ID:          {user_id}")
        print(f"\n   The demo user's data is now available via /api/demo/* endpoints.")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Error seeding demo data: {e}")
        raise
    finally:
        db.close()


# ═════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════


def _get_recent_seasons(count: int) -> list[tuple[int, str]]:
    """Get the most recent N anime seasons.

    Returns list of (year, season) tuples in reverse chronological order.
    Example for count=4 starting from early 2026:
        [(2025, "fall"), (2025, "summer"), (2025, "spring"), (2025, "winter")]
    """
    from datetime import datetime

    now = datetime.now()
    current_year = now.year
    current_month = now.month

    # Determine current season
    if current_month <= 3:
        current_season_idx = 0  # winter
    elif current_month <= 6:
        current_season_idx = 1  # spring
    elif current_month <= 9:
        current_season_idx = 2  # summer
    else:
        current_season_idx = 3  # fall

    seasons_order = ["winter", "spring", "summer", "fall"]
    result: list[tuple[int, str]] = []

    year = current_year
    season_idx = current_season_idx

    for _ in range(count):
        # Go back one season
        season_idx -= 1
        if season_idx < 0:
            season_idx = 3
            year -= 1

        result.append((year, seasons_order[season_idx]))

    return result


if __name__ == "__main__":
    main()
