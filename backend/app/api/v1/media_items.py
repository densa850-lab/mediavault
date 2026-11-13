"""/api/v1/media-items: STUB owned resource that proves per-user ownership checks.

Metadata only (a title). No file storage, upload, URL import or download exists behind it.
Every query is scoped by owner_id, so another user's item is indistinguishable from a missing
one: both return 404.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import MediaItem

router = APIRouter(prefix="/media-items", tags=["media-items (stub)"])

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


class MediaItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MediaItemOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


def _out(item: MediaItem) -> MediaItemOut:
    return MediaItemOut(
        id=item.id, title=item.title, created_at=item.created_at, updated_at=item.updated_at
    )


async def _owned(db: DbSession, user: CurrentUser, item_id: uuid.UUID) -> MediaItem:
    item = (
        await db.execute(
            select(MediaItem).where(MediaItem.id == item_id, MediaItem.owner_id == user.id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise NOT_FOUND
    return item


@router.get("", response_model=list[MediaItemOut])
async def list_items(db: DbSession, user: CurrentUser) -> list[MediaItemOut]:
    rows = await db.execute(
        select(MediaItem)
        .where(MediaItem.owner_id == user.id)
        .order_by(MediaItem.created_at, MediaItem.id)
    )
    return [_out(i) for i in rows.scalars()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MediaItemOut)
async def create_item(body: MediaItemIn, db: DbSession, user: CurrentUser) -> MediaItemOut:
    item = MediaItem(owner_id=user.id, title=body.title)  # owner always comes from the token
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _out(item)


@router.get("/{item_id}", response_model=MediaItemOut)
async def get_item(item_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MediaItemOut:
    return _out(await _owned(db, user, item_id))


@router.patch("/{item_id}", response_model=MediaItemOut)
async def update_item(
    item_id: uuid.UUID, body: MediaItemIn, db: DbSession, user: CurrentUser
) -> MediaItemOut:
    item = await _owned(db, user, item_id)
    item.title = body.title
    await db.commit()
    await db.refresh(item)
    return _out(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Response:
    item = await _owned(db, user, item_id)
    await db.delete(item)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
