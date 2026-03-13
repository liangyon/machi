"""Vector store service — manages ChromaDB for anime embeddings.

This is where the "magic" of RAG happens.  We take the rich text
documents built by the catalog service, turn them into vectors
(arrays of 1536 numbers) using OpenAI's embedding model, and store
them in ChromaDB.  When searching, we embed the query and find the
closest vectors — anime whose descriptions are semantically similar
to what the user is looking for.

How vector search works (conceptual)
─────────────────────────────────────
1. **Embedding**: Text → [0.023, -0.041, 0.087, ...] (1536 floats)
   The embedding model maps text into a high-dimensional space where
   similar meanings are close together.  "dark psychological thriller"
   and "mind games and suspense" end up near each other.

2. **Storage**: ChromaDB stores these vectors alongside metadata
   (genres, year, score) and the original text.

3. **Search**: Query text → embed → find K nearest vectors → return
   those anime.  This is "semantic search" — it understands meaning,
   not just keywords.

4. **Metadata filtering**: Before vector comparison, we can filter
   by metadata (e.g. "only TV anime from 2020+, score > 7.0").
   This narrows the search space and improves relevance.

Why ChromaDB for dev?
─────────────────────
• Zero infrastructure — just a folder on disk (like SQLite for vectors)
• Great LangChain integration via ``langchain-chroma``
• Persistent storage — survives server restarts
• In production we'd swap to pgvector (same interface via LangChain)

Why OpenAI text-embedding-3-small?
──────────────────────────────────
• Cheapest OpenAI embedding model ($0.02 / 1M tokens)
• 1536 dimensions — good balance of quality and storage
• Excellent for our use case (short-to-medium text documents)
• 5,000 anime × ~200 tokens each ≈ 1M tokens ≈ $0.02 total
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import logger


# ── Module-level singleton ───────────────────────────────
# We lazily initialise the vector store on first use.
# This avoids importing heavy ChromaDB/OpenAI deps at module
# load time (which would slow down every test and CLI command).

_vector_store = None
_embeddings = None


def get_embeddings():
    """Get or create the OpenAI embeddings instance.

    Uses ``text-embedding-3-small`` by default (configurable via
    ``OPENAI_EMBEDDING_MODEL`` in .env).

    This is lazy-initialised so we don't hit OpenAI just by
    importing this module.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not configured.
    """
    global _embeddings

    if _embeddings is not None:
        return _embeddings

    if not settings.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not configured. "
            "Get one at https://platform.openai.com/api-keys and add it to .env"
        )

    from langchain_openai import OpenAIEmbeddings

    _embeddings = OpenAIEmbeddings(
        model=settings.OPENAI_EMBEDDING_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
    )

    logger.info(
        "Initialised OpenAI embeddings (model=%s)",
        settings.OPENAI_EMBEDDING_MODEL,
    )
    return _embeddings


def get_vector_store():
    """Get or create the ChromaDB vector store.

    The store is persisted to disk at ``CHROMA_PERSIST_DIR`` so it
    survives server restarts.  The collection name is
    ``CHROMA_COLLECTION_NAME`` (default: "anime_catalog").

    Returns:
        A LangChain ``Chroma`` vector store instance.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not configured.
    """
    global _vector_store

    if _vector_store is not None:
        return _vector_store

    from langchain_chroma import Chroma

    embeddings = get_embeddings()

    # Ensure the persist directory exists
    persist_dir = Path(settings.CHROMA_PERSIST_DIR)
    persist_dir.mkdir(parents=True, exist_ok=True)

    _vector_store = Chroma(
        collection_name=settings.CHROMA_COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(persist_dir),
    )

    logger.info(
        "Initialised ChromaDB vector store (dir=%s, collection=%s)",
        persist_dir,
        settings.CHROMA_COLLECTION_NAME,
    )
    return _vector_store


def reset_vector_store() -> None:
    """Reset the module-level singleton (useful for testing)."""
    global _vector_store, _embeddings
    _vector_store = None
    _embeddings = None


# ═════════════════════════════════════════════════════════
# Adding documents to the vector store
# ═════════════════════════════════════════════════════════


def add_anime_to_store(
    entries: list[dict],
    batch_size: int = 100,
) -> int:
    """Embed and store anime documents in the vector store.

    Each entry should have at minimum:
    - ``mal_id``: int — used as the document ID (for deduplication)
    - ``embedding_text``: str — the text to embed

    Optional metadata fields (used for filtering during search):
    - ``genres``, ``themes``, ``year``, ``mal_score``, ``anime_type``,
      ``mal_members``, ``title``

    Args:
        entries: List of dicts with anime data.
        batch_size: How many to embed at once (OpenAI has token limits).

    Returns:
        Number of documents added/updated.

    How batching works:
        OpenAI's embedding API accepts multiple texts at once.
        We batch to avoid hitting token limits and to show progress.
        100 anime × ~200 tokens each = ~20K tokens per batch (well
        within the 8191 token-per-text limit).
    """
    store = get_vector_store()
    total_added = 0

    for i in range(0, len(entries), batch_size):
        batch = entries[i : i + batch_size]

        texts: list[str] = []
        metadatas: list[dict] = []
        ids: list[str] = []

        for entry in batch:
            mal_id = entry.get("mal_id")
            embedding_text = entry.get("embedding_text", "")

            if not mal_id or not embedding_text:
                continue

            # Document ID = "anime_{mal_id}" for deduplication
            # If we add the same anime twice, ChromaDB updates it
            doc_id = f"anime_{mal_id}"

            # Metadata for filtering during search
            # ChromaDB metadata values must be str, int, float, or bool
            metadata = _build_metadata(entry)

            texts.append(embedding_text)
            metadatas.append(metadata)
            ids.append(doc_id)

        if not texts:
            continue

        # Add to ChromaDB (this calls OpenAI embeddings API)
        store.add_texts(
            texts=texts,
            metadatas=metadatas,
            ids=ids,
        )

        total_added += len(texts)
        logger.info(
            "Embedded batch %d–%d (%d documents, total: %d)",
            i, i + len(batch), len(texts), total_added,
        )

    return total_added


# ═════════════════════════════════════════════════════════
# Searching the vector store
# ═════════════════════════════════════════════════════════


def search_anime(
    query: str,
    k: int = 20,
    filter_dict: dict[str, Any] | None = None,
    score_threshold: float | None = None,
) -> list[dict]:
    """Search the vector store for anime matching a query.

    This is the core retrieval function.  It embeds the query text,
    finds the K nearest vectors in ChromaDB, and returns the results
    with similarity scores.

    Args:
        query: Natural language search query.
            Examples:
            - "dark psychological thriller with mind games"
            - "wholesome slice of life about cooking"
            - "action anime like Cowboy Bebop set in space"
        k: Number of results to return (default 20).
        filter_dict: Optional ChromaDB metadata filter.
            Example: {"anime_type": "TV", "year_gte": 2020}
            See ``_build_chroma_filter()`` for supported filters.
        score_threshold: Optional minimum similarity score (0–1).
            Results below this threshold are excluded.

    Returns:
        List of dicts, each containing:
        - ``mal_id``: int
        - ``title``: str
        - ``embedding_text``: str (the original document)
        - ``metadata``: dict (genres, year, score, etc.)
        - ``similarity_score``: float (0–1, higher = more similar)

    How similarity scoring works:
        ChromaDB uses cosine similarity by default.  A score of 1.0
        means identical vectors (exact semantic match).  In practice,
        good matches are typically 0.3–0.7 for our document type.
    """
    store = get_vector_store()

    # Build ChromaDB where filter if provided
    where_filter = _build_chroma_filter(filter_dict) if filter_dict else None

    # search with scores
    results = store.similarity_search_with_relevance_scores(
        query=query,
        k=k,
        filter=where_filter,
    )

    # Format results
    formatted: list[dict] = []
    for doc, score in results:
        if score_threshold is not None and score < score_threshold:
            continue

        # Extract mal_id from metadata
        metadata = doc.metadata or {}
        mal_id = metadata.get("mal_id", 0)

        formatted.append({
            "mal_id": mal_id,
            "title": metadata.get("title", "Unknown"),
            "embedding_text": doc.page_content,
            "metadata": metadata,
            "similarity_score": round(score, 4),
        })

    return formatted


# ═════════════════════════════════════════════════════════
# Store management
# ═════════════════════════════════════════════════════════


def get_store_stats() -> dict:
    """Get statistics about the vector store.

    Returns:
        Dict with:
        - ``total_documents``: int — number of anime in the store
        - ``collection_name``: str
        - ``persist_directory``: str
    """
    store = get_vector_store()

    # Access the underlying ChromaDB collection for count
    collection = store._collection
    count = collection.count()

    return {
        "total_documents": count,
        "collection_name": settings.CHROMA_COLLECTION_NAME,
        "persist_directory": settings.CHROMA_PERSIST_DIR,
    }


def delete_all_documents() -> int:
    """Delete all documents from the vector store.

    Useful for rebuilding the index from scratch.

    Returns:
        Number of documents that were deleted.
    """
    store = get_vector_store()
    collection = store._collection
    count = collection.count()

    if count > 0:
        # Get all IDs and delete them
        all_data = collection.get()
        if all_data["ids"]:
            collection.delete(ids=all_data["ids"])

    logger.info("Deleted %d documents from vector store", count)
    return count


# ═════════════════════════════════════════════════════════
# Private helpers
# ═════════════════════════════════════════════════════════


def _build_metadata(entry: dict) -> dict:
    """Build ChromaDB metadata dict from an anime entry.

    ChromaDB metadata values must be str, int, float, or bool.
    We can't store lists or nested dicts, so genres/themes stay
    as comma-separated strings.

    We include fields that are useful for filtering during search:
    - ``mal_id`` — for looking up the full entry in our DB
    - ``title`` — for display in results
    - ``genres``, ``themes`` — for genre-based filtering
    - ``year`` — for era-based filtering
    - ``mal_score`` — for quality filtering
    - ``anime_type`` — for format filtering (TV, Movie, etc.)
    - ``mal_members`` — for popularity filtering
    """
    metadata: dict = {}

    # Always include these
    if entry.get("mal_id"):
        metadata["mal_id"] = int(entry["mal_id"])
    if entry.get("title"):
        metadata["title"] = str(entry["title"])

    # Optional fields (only include if present)
    if entry.get("genres"):
        metadata["genres"] = str(entry["genres"])
    if entry.get("themes"):
        metadata["themes"] = str(entry["themes"])
    if entry.get("anime_type"):
        metadata["anime_type"] = str(entry["anime_type"])
    if entry.get("year"):
        metadata["year"] = int(entry["year"])
    if entry.get("mal_score"):
        metadata["mal_score"] = float(entry["mal_score"])
    if entry.get("mal_members"):
        metadata["mal_members"] = int(entry["mal_members"])

    return metadata


def _build_chroma_filter(filter_dict: dict) -> dict | None:
    """Build a ChromaDB ``where`` filter from a user-friendly dict.

    Supports simple equality and range filters:
    - ``{"anime_type": "TV"}`` → exact match
    - ``{"year_gte": 2020}`` → year >= 2020
    - ``{"mal_score_gte": 7.0}`` → score >= 7.0
    - ``{"year_lte": 2010}`` → year <= 2010

    Multiple conditions are combined with ``$and``.

    ChromaDB where filter syntax:
        {"field": {"$gte": value}}  — greater than or equal
        {"field": {"$lte": value}}  — less than or equal
        {"field": value}            — exact match
        {"$and": [cond1, cond2]}    — combine conditions

    Returns:
        ChromaDB where filter dict, or None if no valid filters.
    """
    conditions: list[dict] = []

    for key, value in filter_dict.items():
        if key.endswith("_gte"):
            field = key[:-4]  # Remove "_gte" suffix
            conditions.append({field: {"$gte": value}})
        elif key.endswith("_lte"):
            field = key[:-4]  # Remove "_lte" suffix
            conditions.append({field: {"$lte": value}})
        elif key.endswith("_ne"):
            field = key[:-3]  # Remove "_ne" suffix
            conditions.append({field: {"$ne": value}})
        else:
            # Exact match
            conditions.append({key: value})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}
