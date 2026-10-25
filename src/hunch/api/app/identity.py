"""The caller of the current API request, as the SDK request identity verified it.

`create_app` installs `mainsequence.server.fastapi.install_request_identity` once. Before any route
runs it authenticates the request: hosted, through the platform-signed caller assertion; locally,
through a direct Bearer token checked against `MAINSEQUENCE_ENDPOINT`. It then binds that caller to
the request for `User.get_logged_user()`.

Routes and tools read the caller only through this module. They never read `request.state`, an
identity header, or the process's own SDK user, and nothing replaces a caller the SDK did not
verify.

The Hunch Agent calls the API's MCP tools while it works for a person. On such a call the caller is
the Agent and the platform-signed requester is that person. Ownership follows one identity, the
acting user: the requester on a requester-bound call, the caller on any other, never both combined.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from mainsequence.client import RequestIdentityError, User
from msm.api.http import api_error


@dataclass(frozen=True, slots=True)
class ActingUser:
    """The person a request acts for, with the display name the platform signed, if any."""

    uid: str
    username: str | None


def bound_caller_uid() -> str | None:
    """Return the UID of the request's verified caller, or None when no caller is bound."""
    try:
        return User.get_logged_user().uid
    except RequestIdentityError:
        return None


def caller_uid() -> str:
    """Return the UID of the request's verified caller, or reject the request with 401."""
    uid = bound_caller_uid()
    if uid is None:
        raise unauthenticated()
    return uid


def requester_uid() -> str | None:
    """Return the UID of the person a requester-bound call works for, or None."""
    try:
        requester = User.get_requester()
    except RequestIdentityError:
        return None
    return requester.uid if requester is not None else None


def bound_acting_user() -> ActingUser | None:
    """Return the acting user, or None when no caller is bound."""
    try:
        requester = User.get_requester()
    except RequestIdentityError:
        return None
    if requester is not None:
        return ActingUser(uid=requester.uid, username=getattr(requester, "username", None))
    try:
        caller = User.get_logged_user()
    except RequestIdentityError:
        return None
    return ActingUser(uid=caller.uid, username=getattr(caller, "username", None))


def acting_user() -> ActingUser:
    """Return the acting user, or reject the request with 401."""
    user = bound_acting_user()
    if user is None:
        raise unauthenticated()
    return user


def bound_acting_user_uid() -> str | None:
    """Return the acting user's UID, or None when no caller is bound."""
    user = bound_acting_user()
    return user.uid if user is not None else None


def acting_user_uid() -> str:
    """Return the acting user's UID, or reject the request with 401."""
    return acting_user().uid


def unauthenticated() -> HTTPException:
    return api_error(
        status_code=401,
        code="unauthenticated",
        message="The request has no authenticated caller.",
    )


__all__ = [
    "ActingUser",
    "acting_user",
    "acting_user_uid",
    "bound_acting_user",
    "bound_acting_user_uid",
    "bound_caller_uid",
    "caller_uid",
    "requester_uid",
]
