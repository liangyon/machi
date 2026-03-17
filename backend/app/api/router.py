"""Central API router — aggregates all sub-routers."""

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.api.mal import router as mal_router
from app.api.recommendations import router as recommendations_router
from app.api.watchlist import router as watchlist_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(demo_router)
api_router.include_router(mal_router)
api_router.include_router(recommendations_router)
api_router.include_router(watchlist_router)
