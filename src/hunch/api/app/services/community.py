"""Leaderboard and notifications as the REST routes and the MCP tools present them."""

from __future__ import annotations

import datetime as dt

from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import (
    LeaderboardEntryResource,
    LeaderboardResponse,
    NotificationResource,
    NotificationsResponse,
)
from hunch.community import HunchNotification
from hunch.community.leaderboard import leaderboard_entries
from hunch.community.notifications import list_notifications, mark_read, unread_count
from hunch.profiles.services import profiles_by_uid
from hunch.takes import Take


def leaderboard_response(*, limit: int = 50, today: dt.date | None = None) -> LeaderboardResponse:
    snapshot_date, live, entries = leaderboard_entries(today=today)
    takes = {str(row.uid): row for row in Take.filter(visibility="public", limit=5000)}
    handles = profiles_by_uid([row.owner_user_uid for row in takes.values()])
    items = []
    for entry in entries[:limit]:
        take = takes.get(str(entry["take_uid"]))
        owner = handles.get(take.owner_user_uid) if take else None
        items.append(
            LeaderboardEntryResource(
                rank=entry["rank"],
                take_uid=str(entry["take_uid"]),
                title=take.title if take else None,
                owner_handle=owner.handle if owner else None,
                return_since_activation=entry["return_since_activation"],
                days_active=entry["days_active"],
                value_points=entry.get("value_points", 0),
                is_simulated=entry["is_simulated"],
                is_funded=entry["is_funded"],
                origin_take_uid=str(take.origin_take_uid)
                if take and take.origin_take_uid
                else None,
            )
        )
    return LeaderboardResponse(snapshot_date=snapshot_date, live=live, entries=items)


def notification_resource(row: HunchNotification) -> NotificationResource:
    return NotificationResource(
        uid=str(row.uid),
        kind=row.kind,
        title=row.title,
        body_md=row.body_md,
        take_uid=str(row.take_uid) if row.take_uid else None,
        payload=row.payload_json,
        created_at=row.created_at,
        read_at=row.read_at,
    )


def notifications_response(
    user: ActingUser, *, unread_only: bool = False, limit: int = 50
) -> NotificationsResponse:
    rows = list_notifications(user.uid, unread_only=unread_only)[:limit]
    return NotificationsResponse(
        items=[notification_resource(row) for row in rows], unread=unread_count(user.uid)
    )


def mark_read_response(user: ActingUser, uids: list[str] | None) -> NotificationsResponse:
    mark_read(user.uid, uids)
    return notifications_response(user)


__all__ = [
    "leaderboard_response",
    "mark_read_response",
    "notification_resource",
    "notifications_response",
]
