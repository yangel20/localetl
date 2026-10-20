"""HTTP routers. Each module exposes `router`; `build_api_router` mounts them under /api/v1."""

from fastapi import APIRouter

from app.api import health, pipelines, sources

API_PREFIX = "/api/v1"


def build_api_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(health.router)
    router.include_router(sources.router)
    router.include_router(pipelines.router)
    return router
