"""Reading takes for the acting user.

Authorisation is decided here, on the Hunch tables: a person reads their own takes and any public
take. ms-markets rows behind a take are never returned without passing through this check.
"""

from __future__ import annotations

import uuid

from hunch.api.app.schemas import TakeListResponse, TakeResource
from hunch.takes import Take


def take_resource(row: Take) -> TakeResource:
    return TakeResource(
        uid=str(row.uid),
        owner_user_uid=row.owner_user_uid,
        title=row.title,
        thesis_text=row.thesis_text,
        constraints=row.constraints_json,
        status=row.status,
        execution_mode=row.execution_mode,
        visibility=row.visibility,
        forked_from_take_uid=str(row.forked_from_take_uid) if row.forked_from_take_uid else None,
        origin_take_uid=str(row.origin_take_uid) if row.origin_take_uid else None,
        signal_uid=row.signal_uid,
        activated_at=row.activated_at,
        published_at=row.published_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_takes_for_user(user_uid: str, *, limit: int = 25, offset: int = 0) -> TakeListResponse:
    """The acting user's own takes, newest first, as one bounded page."""
    rows = Take.filter(owner_user_uid=user_uid, limit=offset + limit)
    rows = sorted(rows, key=lambda row: (row.created_at is None, row.created_at), reverse=True)
    window = rows[offset : offset + limit]
    return TakeListResponse(
        items=[take_resource(row) for row in window],
        limit=limit,
        offset=offset,
        returned=len(window),
    )


def get_take_for_user(take_uid: str, user_uid: str) -> TakeResource | None:
    """One take the acting user may read: their own, or a public one. None otherwise."""
    try:
        resolved = uuid.UUID(str(take_uid))
    except ValueError as exc:
        raise ValueError("take_uid must be a UUID.") from exc
    row = Take.get_by_uid(resolved)
    if row is None:
        return None
    if row.owner_user_uid != user_uid and row.visibility != "public":
        return None
    return take_resource(row)


__all__ = ["get_take_for_user", "list_takes_for_user", "take_resource"]
