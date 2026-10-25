"""Take lifecycle: create, edit, publish, fork, archive, and who may read what.

Authorisation is decided here, on Hunch rows: a person reads their own takes and any published
take; only the owner changes a take. A missing or invisible take raises ``LookupError`` (404) so
private takes are not revealed; an action the state does not allow raises ``TakeStateError``
(409).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hunch.profiles import utc_now
from hunch.profiles.services import ensure_profile
from hunch.settings import EXECUTION_MODES, TAKE_STATUSES
from hunch.takes import Take

ListScope = Literal["mine", "public"]
ExecutionMode = Literal["practice", "approval", "autopilot"]
RiskLevel = Literal["low", "medium", "high"]

# A take can be published once Hunch has built it; drafts have nothing to show.
PUBLISHABLE_STATUSES = frozenset({"built", "active_practice", "funding", "active_funded"})
# The row API returns at most this many rows per scan; lists paginate in memory.
LIST_SCAN_LIMIT = 2000


class TakeStateError(ValueError):
    """The take's state does not allow the requested action."""


class TakeConstraints(BaseModel):
    """What the person asked Hunch to respect when it builds and manages the basket."""

    model_config = ConfigDict(extra="forbid")

    horizon_months: int = Field(default=12, ge=1, le=120)
    cash_buffer: float = Field(default=0.05, ge=0.0, le=0.5)
    max_single_name_weight: float = Field(default=0.15, ge=0.02, le=1.0)
    max_positions: int = Field(default=15, ge=3, le=40)
    exclusions: list[str] = Field(default_factory=list, max_length=50)
    allow_leveraged_etf: bool = False
    risk_level: RiskLevel = "medium"
    change_my_mind: str | None = Field(default=None, max_length=2000)

    @field_validator("exclusions")
    @classmethod
    def _normalize_exclusions(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value and value.strip()]
        return list(dict.fromkeys(cleaned))


class TakeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    thesis_text: str = Field(min_length=10, max_length=5000)
    constraints: TakeConstraints = Field(default_factory=TakeConstraints)
    execution_mode: ExecutionMode = "practice"

    @field_validator("title", "thesis_text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank.")
        return stripped


class TakeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    thesis_text: str | None = Field(default=None, min_length=10, max_length=5000)
    constraints: TakeConstraints | None = None


def _take_uid(value: uuid.UUID | str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ValueError("take_uid must be a UUID.") from exc


def visible_to(row: Take, viewer_uid: str) -> bool:
    if row.owner_user_uid == viewer_uid:
        return True
    return row.visibility == "public" and row.status != "archived"


def get_take_for(viewer_uid: str, take_uid: uuid.UUID | str) -> Take:
    """One take the viewer may read: their own, or a published one."""
    row = Take.get_by_uid(_take_uid(take_uid))
    if row is None or not visible_to(row, viewer_uid):
        raise LookupError(f"Take {take_uid} does not exist.")
    return row


def owned_take(owner_user_uid: str, take_uid: uuid.UUID | str) -> Take:
    """One take the person owns; others are reported as missing."""
    row = Take.get_by_uid(_take_uid(take_uid))
    if row is None or row.owner_user_uid != owner_user_uid:
        raise LookupError(f"Take {take_uid} does not exist.")
    return row


def _sort_newest_first(rows: Sequence[Take]) -> list[Take]:
    return sorted(rows, key=lambda row: (row.created_at is None, row.created_at), reverse=True)


def list_takes(
    viewer_uid: str,
    *,
    scope: ListScope = "mine",
    status: str | None = None,
    search: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[Take], int]:
    """One page of takes plus the total, newest first.

    `mine` lists the viewer's own takes in every status; `public` lists published takes of
    everyone, archived ones excluded.
    """
    if scope == "mine":
        rows = Take.filter(owner_user_uid=viewer_uid, limit=LIST_SCAN_LIMIT)
    else:
        rows = [
            row
            for row in Take.filter(visibility="public", limit=LIST_SCAN_LIMIT)
            if row.status != "archived"
        ]
    if status is not None:
        if status not in TAKE_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(TAKE_STATUSES)}.")
        rows = [row for row in rows if row.status == status]
    if search:
        needle = search.strip().lower()
        rows = [
            row for row in rows if needle in row.title.lower() or needle in row.thesis_text.lower()
        ]
    ordered = _sort_newest_first(rows)
    return ordered[offset : offset + limit], len(ordered)


def create_take(owner_user_uid: str, payload: TakeCreate, *, username: str | None = None) -> Take:
    ensure_profile(owner_user_uid, username=username)
    now = utc_now()
    return Take.create(
        owner_user_uid=owner_user_uid,
        title=payload.title,
        thesis_text=payload.thesis_text,
        constraints_json=payload.constraints.model_dump(),
        status="draft",
        execution_mode=payload.execution_mode,
        visibility="private",
        created_at=now,
        updated_at=now,
    )


def update_take(owner_user_uid: str, take_uid: uuid.UUID | str, payload: TakeUpdate) -> Take:
    row = owned_take(owner_user_uid, take_uid)
    if row.status == "archived":
        raise TakeStateError("An archived take cannot be edited.")
    values: dict[str, object] = {}
    if payload.title is not None:
        values["title"] = payload.title.strip()
    if payload.thesis_text is not None:
        values["thesis_text"] = payload.thesis_text.strip()
    if payload.constraints is not None:
        values["constraints_json"] = payload.constraints.model_dump()
    if not values:
        return row
    values["updated_at"] = utc_now()
    return Take.update(row.uid, **values)


def set_execution_mode(owner_user_uid: str, take_uid: uuid.UUID | str, mode: str) -> Take:
    if mode not in EXECUTION_MODES:
        raise ValueError(f"execution_mode must be one of: {', '.join(EXECUTION_MODES)}.")
    row = owned_take(owner_user_uid, take_uid)
    if row.status == "archived":
        raise TakeStateError("An archived take cannot change its execution mode.")
    if row.execution_mode == mode:
        return row
    return Take.update(row.uid, execution_mode=mode, updated_at=utc_now())


def publish_take(owner_user_uid: str, take_uid: uuid.UUID | str) -> Take:
    row = owned_take(owner_user_uid, take_uid)
    if row.status not in PUBLISHABLE_STATUSES:
        raise TakeStateError("Build the take before publishing it.")
    if row.visibility == "public":
        return row
    now = utc_now()
    return Take.update(row.uid, visibility="public", published_at=now, updated_at=now)


def unpublish_take(owner_user_uid: str, take_uid: uuid.UUID | str) -> Take:
    row = owned_take(owner_user_uid, take_uid)
    if row.visibility == "private":
        return row
    return Take.update(row.uid, visibility="private", updated_at=utc_now())


def archive_take(owner_user_uid: str, take_uid: uuid.UUID | str, confirmation: str) -> Take:
    """Archive after the person typed the exact confirmation `DELETE <uid>`."""
    row = owned_take(owner_user_uid, take_uid)
    expected = f"DELETE {row.uid}"
    if confirmation.strip() != expected:
        raise ValueError(f"Confirm the archive by sending exactly: {expected}")
    if row.status == "archived":
        return row
    return Take.update(row.uid, status="archived", visibility="private", updated_at=utc_now())


def fork_take(
    forker_user_uid: str,
    source_take_uid: uuid.UUID | str,
    *,
    username: str | None = None,
) -> Take:
    """Copy a published (or own) take into an independent private draft with lineage."""
    source = get_take_for(forker_user_uid, source_take_uid)
    if source.status == "archived":
        raise TakeStateError("An archived take cannot be forked.")
    ensure_profile(forker_user_uid, username=username)
    now = utc_now()
    return Take.create(
        owner_user_uid=forker_user_uid,
        title=source.title,
        thesis_text=source.thesis_text,
        constraints_json=source.constraints_json,
        status="draft",
        execution_mode="practice",
        visibility="private",
        forked_from_take_uid=source.uid,
        origin_take_uid=source.origin_take_uid or source.uid,
        created_at=now,
        updated_at=now,
    )


__all__ = [
    "LIST_SCAN_LIMIT",
    "PUBLISHABLE_STATUSES",
    "TakeConstraints",
    "TakeCreate",
    "TakeStateError",
    "TakeUpdate",
    "archive_take",
    "create_take",
    "fork_take",
    "get_take_for",
    "list_takes",
    "owned_take",
    "publish_take",
    "set_execution_mode",
    "unpublish_take",
    "update_take",
    "visible_to",
]
