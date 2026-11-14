"""GET /api/v1/health: liveness plus a real database check."""

import asyncio
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.core.logging import log
from app.db.session import ping

router = APIRouter(tags=["system"])

CheckState = Literal["ok", "error"]


class HealthChecks(BaseModel):
    database: CheckState


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    checks: HealthChecks
    time: datetime


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is down"}},
)
async def health(request: Request, response: Response) -> HealthResponse:
    settings = request.app.state.settings
    engine = request.app.state.engine
    db_state: CheckState = "ok"
    try:
        await asyncio.wait_for(ping(engine), timeout=settings.database_connect_timeout_s + 2)
    except Exception as exc:  # noqa: BLE001 - any failure means "not healthy"
        db_state = "error"
        # Log the type only: connection errors can echo hostnames or usernames.
        log.warning("health.database_unavailable", error_type=type(exc).__name__)

    healthy = db_state == "ok"
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment_name,
        checks=HealthChecks(database=db_state),
        time=datetime.now(UTC),
    )
