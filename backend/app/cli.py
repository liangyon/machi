"""CLI commands for Machi backend operations.

This module provides command-line tools for operations that are too
long-running or infrastructure-level for API endpoints:

• ``ingest-anime`` — Populate the anime knowledge base from Jikan API
  and embed into the vector store.

Usage:
    # From the backend directory:
    uv run python -m app.cli ingest-anime --pages 10
    uv run python -m app.cli ingest-anime --pages 2 --skip-embed  # DB only, no vectors
    uv run python -m app.cli stats  # Show catalog and vector store stats

    # Or via Makefile:
    make ingest-anime
    make ingest-anime-small  # Quick test with 2 pages

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

    args = parser.parse_args()

    if args.command == "ingest-anime":
        asyncio.run(cmd_ingest_anime(args))
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "embed":
        cmd_embed()
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

    # ── Step 1: Fetch top anime ──────────────────────────
    print(f"\n🔍 Fetching top anime ({args.pages} pages × 25 = up to {args.pages * 25} anime)...")

    def on_page(page, total):
        print(f"   Page {page}/{args.pages} — {total} anime so far")

    raw_top = await fetch_top_anime(pages=args.pages, on_page=on_page)
    print(f"   ✅ Got {len(raw_top)} top anime\n")

    # ── Step 2: Fetch recent seasons ─────────────────────
    raw_seasonal: list[dict] = []
    if args.seasons > 0:
        print(f"🗓️  Fetching {args.seasons} recent seasons...")
        seasons_list = _get_recent_seasons(args.seasons)

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
        parsed = parse_jikan_to_catalog(raw, source=f"seasonal")
        if parsed.get("mal_id"):
            all_parsed.append(parsed)

    print(f"   ✅ Parsed {len(all_parsed)} anime entries\n")

    # ── Step 4: Upsert into database ─────────────────────
    print("💾 Saving to database (upserting by MAL ID)...")
    db = SessionLocal()
    try:
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
