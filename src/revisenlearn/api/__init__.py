from fastapi import APIRouter

from . import (
    backup,
    concepts,
    hierarchy,
    meta,
    notes,
    resources,
    search,
    settings,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(hierarchy.router, tags=["hierarchy"])
api_router.include_router(notes.router, tags=["notes"])
api_router.include_router(resources.router, tags=["resources"])
api_router.include_router(concepts.router, tags=["concepts"])
api_router.include_router(search.router, tags=["search"])
api_router.include_router(backup.router, tags=["backup"])
api_router.include_router(settings.router, tags=["settings"])

__all__ = ["api_router"]
