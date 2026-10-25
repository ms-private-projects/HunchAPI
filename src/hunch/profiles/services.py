"""Hunch user profiles: created on first contact, edited by their owner."""

from __future__ import annotations

import re
from collections.abc import Iterable

from hunch.profiles import HunchUserProfile, utc_now

HANDLE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{2,31}$")
_INVALID_HANDLE_CHARACTERS = re.compile(r"[^a-z0-9_]+")


def normalize_handle(value: str) -> str:
    """Lower-case, replace invalid characters, and validate a public handle."""
    candidate = _INVALID_HANDLE_CHARACTERS.sub("_", value.strip().lower()).strip("_")
    if not HANDLE_PATTERN.fullmatch(candidate):
        raise ValueError(
            "handle must be 3 to 32 characters of lower-case letters, digits and underscores."
        )
    return candidate


def suggested_handle(user_uid: str, username: str | None) -> str:
    """A handle from the person's username (its local part), else from their user UID."""
    if username:
        local_part = username.split("@", 1)[0]
        try:
            return normalize_handle(local_part)
        except ValueError:
            pass
    return f"user_{user_uid.replace('-', '')[:8].lower()}"


def _unique_handle(base: str) -> str:
    handle = base
    suffix = 2
    while HunchUserProfile.filter(handle=handle, limit=1):
        handle = f"{base[: 32 - len(str(suffix)) - 1]}_{suffix}"
        suffix += 1
    return handle


def ensure_profile(user_uid: str, *, username: str | None = None) -> HunchUserProfile:
    """Return the person's profile, creating it on first contact.

    The UID comes from the verified request identity, never from a request body.
    """
    existing = HunchUserProfile.get_by_uid(user_uid)
    if existing is not None:
        return existing
    now = utc_now()
    return HunchUserProfile.create(
        user_uid=user_uid,
        handle=_unique_handle(suggested_handle(user_uid, username)),
        display_name=username,
        created_at=now,
        updated_at=now,
    )


def update_profile(
    user_uid: str,
    *,
    handle: str | None = None,
    display_name: str | None = None,
) -> HunchUserProfile:
    """Change the person's own handle or display name."""
    profile = ensure_profile(user_uid)
    values: dict[str, object] = {}
    if handle is not None:
        normalized = normalize_handle(handle)
        if normalized != profile.handle:
            taken = HunchUserProfile.filter(handle=normalized, limit=1)
            if taken and taken[0].user_uid != user_uid:
                raise ValueError("That handle is already taken.")
            values["handle"] = normalized
    if display_name is not None:
        values["display_name"] = display_name.strip() or None
    if not values:
        return profile
    values["updated_at"] = utc_now()
    return HunchUserProfile.update(user_uid, **values)


def profiles_by_uid(user_uids: Iterable[str]) -> dict[str, HunchUserProfile]:
    """Profiles for attribution (handles on shared takes and the leaderboard)."""
    found: dict[str, HunchUserProfile] = {}
    for user_uid in dict.fromkeys(user_uids):
        profile = HunchUserProfile.get_by_uid(user_uid)
        if profile is not None:
            found[user_uid] = profile
    return found


__all__ = [
    "HANDLE_PATTERN",
    "ensure_profile",
    "normalize_handle",
    "profiles_by_uid",
    "suggested_handle",
    "update_profile",
]
