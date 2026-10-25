"""The acting user's profile."""

from __future__ import annotations

from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import ProfileResource
from hunch.profiles import HunchUserProfile
from hunch.profiles.services import ensure_profile, update_profile


def profile_resource(row: HunchUserProfile) -> ProfileResource:
    metadata = row.metadata_json or {}
    return ProfileResource(
        user_uid=row.user_uid,
        handle=row.handle,
        display_name=row.display_name,
        email_digest=bool(metadata.get("email_digest", False)),
        email_address=metadata.get("email_address"),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_profile(user: ActingUser) -> ProfileResource:
    return profile_resource(ensure_profile(user.uid, username=user.username))


def patch_profile(
    user: ActingUser,
    *,
    handle: str | None = None,
    display_name: str | None = None,
    email_digest: bool | None = None,
    email_address: str | None = None,
) -> ProfileResource:
    ensure_profile(user.uid, username=user.username)
    return profile_resource(
        update_profile(
            user.uid,
            handle=handle,
            display_name=display_name,
            email_digest=email_digest,
            email_address=email_address,
        )
    )


__all__ = ["get_profile", "patch_profile", "profile_resource"]
