from fastapi import APIRouter

from app.api.v1 import auth, health, media_items

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(media_items.router)
