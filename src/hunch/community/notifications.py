"""The in-app notification feed: created by services and Jobs, read by the site and the Agent."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from hunch.community import HunchNotification
from hunch.profiles import utc_now
from hunch.settings import NOTIFICATION_KINDS


def notify(
    user_uid: str,
    kind: str,
    title: str,
    *,
    body_md: str = "",
    take_uid: uuid.UUID | str | None = None,
    payload: dict[str, Any] | None = None,
    created_at: dt.datetime | None = None,
) -> HunchNotification:
    """Append one notification for one Hunch user."""
    if kind not in NOTIFICATION_KINDS:
        raise ValueError(f"Unknown notification kind {kind!r}.")
    return HunchNotification.create(
        user_uid=user_uid,
        take_uid=uuid.UUID(str(take_uid)) if take_uid is not None else None,
        kind=kind,
        title=title[:255],
        body_md=body_md,
        payload_json=payload,
        created_at=created_at or utc_now(),
        delivered_channels_json=["app"],
    )


def list_notifications(
    user_uid: str,
    *,
    unread_only: bool = False,
    take_uid: uuid.UUID | str | None = None,
) -> list[HunchNotification]:
    """The user's notifications, newest first."""
    filters: dict[str, Any] = {"user_uid": user_uid}
    if take_uid is not None:
        filters["take_uid"] = uuid.UUID(str(take_uid))
    rows = HunchNotification.filter(**filters)
    if unread_only:
        rows = [row for row in rows if row.read_at is None]
    return sorted(
        rows, key=lambda row: (row.created_at or dt.datetime.min, str(row.uid)), reverse=True
    )


def unread_count(user_uid: str) -> int:
    return sum(1 for row in HunchNotification.filter(user_uid=user_uid) if row.read_at is None)


def mark_read(
    user_uid: str,
    uids: Iterable[uuid.UUID | str] | None = None,
    *,
    read_at: dt.datetime | None = None,
) -> list[HunchNotification]:
    """Mark the given notifications (default: every unread one) of this user as read."""
    moment = read_at or utc_now()
    wanted = {str(uid) for uid in uids} if uids is not None else None
    updated: list[HunchNotification] = []
    for row in HunchNotification.filter(user_uid=user_uid):
        if row.read_at is not None:
            continue
        if wanted is not None and str(row.uid) not in wanted:
            continue
        updated.append(HunchNotification.update(row.uid, read_at=moment))
    return updated


def notifications_for_takes(
    user_uid: str, take_uids: Sequence[uuid.UUID]
) -> list[HunchNotification]:
    wanted = {str(uid) for uid in take_uids}
    return [row for row in list_notifications(user_uid) if str(row.take_uid) in wanted]


__all__ = [
    "list_notifications",
    "mark_read",
    "notifications_for_takes",
    "notify",
    "unread_count",
]
