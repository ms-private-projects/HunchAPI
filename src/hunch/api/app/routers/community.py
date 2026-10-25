"""Leaderboard and notifications."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..errors import api_http_error
from ..identity import acting_user
from ..schemas import LeaderboardResponse, MarkReadRequest, NotificationsResponse
from ..services.community import leaderboard_response, mark_read_response, notifications_response

leaderboard_router = APIRouter(prefix="/v1/leaderboard", tags=["Leaderboard"])
notifications_router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])


@leaderboard_router.get(
    "",
    response_model=LeaderboardResponse,
    summary="Leaderboard",
    description="Published takes ranked by return since activation (latest snapshot, or live).",
)
def leaderboard(limit: int = Query(default=50, ge=1, le=200)) -> LeaderboardResponse:
    try:
        return leaderboard_response(limit=limit)
    except Exception as exc:
        raise api_http_error(exc) from exc


@notifications_router.get("", response_model=NotificationsResponse, summary="My notifications")
def notifications(
    unread_only: bool = Query(default=False), limit: int = Query(default=50, ge=1, le=200)
) -> NotificationsResponse:
    try:
        return notifications_response(acting_user(), unread_only=unread_only, limit=limit)
    except Exception as exc:
        raise api_http_error(exc) from exc


@notifications_router.post(
    "/actions/mark-read", response_model=NotificationsResponse, summary="Mark notifications read"
)
def mark_read(payload: MarkReadRequest | None = None) -> NotificationsResponse:
    try:
        return mark_read_response(acting_user(), payload.uids if payload else None)
    except Exception as exc:
        raise api_http_error(exc) from exc
