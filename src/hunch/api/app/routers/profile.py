"""The acting user's profile."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import api_http_error
from ..identity import acting_user
from ..schemas import ProfileResource, ProfileUpdateRequest
from ..services.profile import get_profile, patch_profile

router = APIRouter(prefix="/v1/profile", tags=["Profile"])


@router.get(
    "",
    response_model=ProfileResource,
    summary="My profile",
    description="Return the acting user's Hunch profile, creating it on first contact.",
)
def read_profile() -> ProfileResource:
    try:
        return get_profile(acting_user())
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.patch(
    "",
    response_model=ProfileResource,
    summary="Update my profile",
    description="Change the acting user's public handle or display name.",
)
def update_profile(payload: ProfileUpdateRequest) -> ProfileResource:
    try:
        return patch_profile(
            acting_user(), handle=payload.handle, display_name=payload.display_name
        )
    except Exception as exc:
        raise api_http_error(exc) from exc
