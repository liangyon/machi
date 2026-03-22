"""Cauldron API endpoints — seed-based vibe-matching recommendations.

Cauldron lets users pick 1–3 seed anime and get recommendations that
match the vibe of those seeds — no MAL/AniList import required.

Endpoint design mirrors /api/recommendations exactly:
  POST /generate    — expensive (calls LLM, ~3-5 seconds).  Returns job_id.
  GET  /status/{job_id} — polls job progress.
  GET  /results/{session_id} — loads completed cauldron session.
  GET  /search?q=   — fast seed search against AnimeCatalogEntry.

The job polling pattern is the same as /recommendations so the frontend
can share the useJobPoller hook for both.
"""

from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.exceptions import AppError
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.anime import AnimeCatalogEntry
from app.models.recommendation import RecommendationEntry, RecommendationSession
from app.models.user import User
from app.schemas.cauldron import (
    CauldronGenerateRequest,
    CauldronResultsResponse,
    CauldronSearchResponse,
    CauldronSearchResult,
)
from app.schemas.recommendation import (
    RecommendationGenerateAccepted,
    RecommendationItem,
    RecommendationJobStatusResponse,
)
from app.services.cauldron import generate_cauldron_recommendations

router = APIRouter(prefix="/cauldron", tags=["Cauldron"])

# Separate in-process job store for cauldron jobs.
# Kept separate from _generation_jobs in recommendations.py so there's no
# cross-contamination between the two polling namespaces.
_cauldron_jobs: dict[str, dict] = {}
_cauldron_jobs_lock = Lock()


# ═════════════════════════════════════════════════════════
# GET /api/cauldron/search?q=...
# ═════════════════════════════════════════════════════════


@router.get("/search", response_model=CauldronSearchResponse)
def search_seeds(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search the anime catalog for seed candidates.

    Returns up to 10 results matching the query against title and
    title_english.  Ordered by MAL score descending so well-known
    anime float to the top.

    Only anime in the Machi catalog (AnimeCatalogEntry) can be used as
    seeds because the retrieval pipeline requires them to be embedded.
    """
    results = db.execute(
        select(AnimeCatalogEntry)
        .where(
            or_(
                AnimeCatalogEntry.title.ilike(f"%{q}%"),
                AnimeCatalogEntry.title_english.ilike(f"%{q}%"),
            )
        )
        .order_by(AnimeCatalogEntry.mal_score.desc().nulls_last())
        .limit(10)
    ).scalars().all()

    items = [
        CauldronSearchResult(
            mal_id=r.mal_id,
            title=r.title,
            title_english=r.title_english,
            image_url=r.image_url,
            year=r.year,
            anime_type=r.anime_type,
            genres=r.genres,
            mal_score=r.mal_score,
        )
        for r in results
    ]

    return CauldronSearchResponse(results=items, total=len(items))


# ═════════════════════════════════════════════════════════
# POST /api/cauldron/generate
# ═════════════════════════════════════════════════════════


@router.post("/generate", response_model=RecommendationGenerateAccepted, status_code=202)
def generate_cauldron(
    body: CauldronGenerateRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a cauldron recommendation generation job.

    Unlike /recommendations/generate, this endpoint does NOT require a
    preference profile.  The seed anime replace the profile as the signal.

    Validates that:
    - 1–3 seed_mal_ids are provided (enforced by CauldronGenerateRequest)
    - No duplicates (enforced by the schema validator)
    - All seeds exist in the anime catalog (fast DB check here)

    Returns a job_id immediately.  The frontend polls /status/{job_id}.
    """
    # Validate all seeds exist in catalog
    found_count = db.execute(
        select(AnimeCatalogEntry.mal_id).where(
            AnimeCatalogEntry.mal_id.in_(body.seed_mal_ids)
        )
    ).scalars().all()

    if len(found_count) != len(body.seed_mal_ids):
        missing = set(body.seed_mal_ids) - set(found_count)
        raise AppError(
            code="NOT_FOUND",
            message=f"One or more seed anime not found in catalog: {sorted(missing)}.",
            status_code=404,
        )

    job_id = str(uuid4())
    _set_job(
        job_id,
        {
            "job_id": job_id,
            "user_id": user.id,
            "seed_mal_ids": body.seed_mal_ids,
            "status": "queued",
            "progress": 0,
            "stage": "queued",
            "error": None,
            "session_id": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    background_tasks.add_task(
        _run_cauldron_job,
        job_id,
        user.id,
        body.seed_mal_ids,
        body.num_recommendations,
    )

    logger.info(
        "cauldron_job_enqueued job_id=%s user_id=%s seeds=%s num=%d",
        job_id,
        user.id,
        body.seed_mal_ids,
        body.num_recommendations,
    )

    return RecommendationGenerateAccepted(
        job_id=job_id,
        status="queued",
        progress=0,
        stage="queued",
    )


# ═════════════════════════════════════════════════════════
# GET /api/cauldron/status/{job_id}
# ═════════════════════════════════════════════════════════


@router.get("/status/{job_id}", response_model=RecommendationJobStatusResponse)
def get_cauldron_status(
    job_id: str,
    user: User = Depends(get_current_user),
):
    """Poll the status of a cauldron generation job."""
    job = _get_job(job_id)

    if not job or job.get("user_id") != user.id:
        raise AppError(
            code="NOT_FOUND",
            message="Cauldron job not found.",
            status_code=404,
        )

    return RecommendationJobStatusResponse(
        job_id=job_id,
        status=job.get("status", "queued"),
        progress=int(job.get("progress", 0)),
        stage=job.get("stage", "queued"),
        error=job.get("error"),
        session_id=job.get("session_id"),
    )


# ═════════════════════════════════════════════════════════
# GET /api/cauldron/results/{session_id}
# ═════════════════════════════════════════════════════════


@router.get("/results/{session_id}", response_model=CauldronResultsResponse)
def get_cauldron_results(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Load a completed cauldron session's recommendations.

    Also resolves the seed MAL IDs to titles so the frontend can display
    "Based on: Vinland Saga, Berserk, Kingdom".
    """
    session_record = db.execute(
        select(RecommendationSession).where(
            RecommendationSession.id == session_id,
            RecommendationSession.user_id == user.id,
            RecommendationSession.mode == "cauldron",
        )
    ).scalar_one_or_none()

    if not session_record:
        raise AppError(
            code="NOT_FOUND",
            message="Cauldron session not found.",
            status_code=404,
        )

    # Resolve seed MAL IDs → titles
    seed_ids: list[int] = session_record.cauldron_seed_ids or []
    seed_titles: list[str] = []
    if seed_ids:
        seed_entries = db.execute(
            select(AnimeCatalogEntry.mal_id, AnimeCatalogEntry.title).where(
                AnimeCatalogEntry.mal_id.in_(seed_ids)
            )
        ).all()
        # Preserve original order
        title_map = {row.mal_id: row.title for row in seed_entries}
        seed_titles = [title_map.get(sid, f"Unknown ({sid})") for sid in seed_ids]

    recommendation_items = [
        RecommendationItem(
            mal_id=entry.mal_id,
            title=entry.title,
            image_url=entry.image_url,
            genres=entry.genres or "",
            themes=entry.themes or "",
            synopsis=entry.synopsis or "",
            mal_score=entry.mal_score,
            year=entry.year,
            anime_type=entry.anime_type,
            reasoning=entry.reasoning,
            confidence=entry.confidence,
            similar_to=entry.similar_to or [],
            similarity_score=entry.similarity_score,
            preference_score=entry.preference_score,
            combined_score=entry.combined_score,
            is_fallback=entry.is_fallback,
        )
        for entry in session_record.entries
    ]

    return CauldronResultsResponse(
        session_id=session_record.id,
        seed_titles=seed_titles,
        recommendations=recommendation_items,
        generated_at=session_record.generated_at,
        total=len(recommendation_items),
        used_fallback=session_record.used_fallback,
    )


# ═════════════════════════════════════════════════════════
# Private helpers — job store
# ═════════════════════════════════════════════════════════


def _set_job(job_id: str, payload: dict) -> None:
    with _cauldron_jobs_lock:
        _cauldron_jobs[job_id] = payload


def _get_job(job_id: str) -> dict | None:
    with _cauldron_jobs_lock:
        job = _cauldron_jobs.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **updates) -> None:
    with _cauldron_jobs_lock:
        current = _cauldron_jobs.get(job_id)
        if not current:
            return
        current.update(updates)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        _cauldron_jobs[job_id] = current


# ═════════════════════════════════════════════════════════
# Background task
# ═════════════════════════════════════════════════════════


def _run_cauldron_job(
    job_id: str,
    user_id: str,
    seed_mal_ids: list[int],
    num_recommendations: int,
) -> None:
    """Background task that runs cauldron generation and persists results."""
    db = SessionLocal()
    try:
        _update_job(job_id, status="running", progress=10, stage="validating")

        _update_job(job_id, progress=30, stage="fetching_seeds")

        _update_job(job_id, progress=50, stage="retrieving_candidates")

        _update_job(job_id, progress=75, stage="generating_recommendations")

        raw_recommendations = generate_cauldron_recommendations(
            seed_mal_ids=seed_mal_ids,
            num_recommendations=num_recommendations,
            db=db,
            user_id=user_id,
        )

        _update_job(job_id, progress=90, stage="persisting")

        used_fallback = any(rec.get("is_fallback", False) for rec in raw_recommendations)

        session_record = RecommendationSession(
            user_id=user_id,
            mode="cauldron",
            cauldron_seed_ids=seed_mal_ids,
            custom_query=None,
            used_fallback=used_fallback,
            total_count=len(raw_recommendations),
        )
        db.add(session_record)
        db.flush()

        for rec in raw_recommendations:
            entry = RecommendationEntry(
                session_id=session_record.id,
                mal_id=rec.get("mal_id", 0),
                title=rec.get("title", "Unknown"),
                image_url=rec.get("image_url"),
                genres=rec.get("genres", ""),
                themes=rec.get("themes", ""),
                synopsis=rec.get("synopsis", ""),
                mal_score=rec.get("mal_score"),
                year=rec.get("year"),
                anime_type=rec.get("anime_type"),
                reasoning=rec.get("reasoning", "No reasoning provided."),
                confidence=rec.get("confidence", "medium"),
                similar_to=rec.get("similar_to", []),
                similarity_score=rec.get("similarity_score", 0.0),
                preference_score=rec.get("preference_score", 0.0),
                combined_score=rec.get("combined_score", 0.0),
                is_fallback=rec.get("is_fallback", False),
            )
            db.add(entry)

        db.commit()

        _update_job(
            job_id,
            status="succeeded",
            progress=100,
            stage="completed",
            session_id=session_record.id,
            error=None,
        )

        logger.info(
            "cauldron_job_succeeded job_id=%s session_id=%s seeds=%s recs=%d",
            job_id,
            session_record.id,
            seed_mal_ids,
            len(raw_recommendations),
        )

    except ValueError as e:
        _update_job(job_id, status="failed", progress=0, stage="failed", error=str(e))
        logger.warning("cauldron_job_failed job_id=%s (ValueError): %s", job_id, e)
    except RuntimeError as e:
        _update_job(job_id, status="failed", progress=0, stage="failed", error=str(e))
        logger.error("cauldron_job_failed job_id=%s (RuntimeError): %s", job_id, e)
    except Exception as e:
        _update_job(
            job_id,
            status="failed",
            progress=0,
            stage="failed",
            error="An unexpected error occurred. Please try again.",
        )
        logger.exception("cauldron_job_failed job_id=%s (unhandled): %s", job_id, e)
    finally:
        db.close()
