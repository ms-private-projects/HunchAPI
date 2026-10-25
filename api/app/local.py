"""Explicit single-developer, loopback-only launcher of the Hunch API.

The deployed entrypoint remains ``api.app.main:app``. Its installed request identity runs here in
local mode, where it verifies a direct Bearer token with the Main Sequence backend. This launcher
presents the SDK sign-in of this process as that token on every loopback request, so the Vite dev
server can proxy ``/api`` and the local Tau runtime can reach ``/mcp`` without a credential of
their own. The only caller is the signed-in developer. It must never be used behind a public proxy.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from hunch.api.app.main import create_app as create_hunch_app
from mainsequence.client.exceptions import AuthenticationError
from mainsequence.client.utils import get_authorization_headers

LOCAL_SIGN_IN_TIMEOUT_SECONDS = 20
# A direct caller cannot claim an identity or present a credential. The only user in this explicit
# local mode is the account signed into the SDK process.
CALLER_HEADERS = frozenset(
    {
        b"authorization",
        b"x-mainsequence-caller-assertion",
        b"x-public-ingress",
        b"x-user-id",
        b"x-user-uid",
        b"x-username",
    }
)
# Routes the local launcher answers without a sign-in: process liveness only.
ANONYMOUS_ROUTES = frozenset({("GET", "/healthz")})


def _is_loopback(request: Request) -> bool:
    if request.client is None:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


@contextmanager
def _public_ingress(routes: frozenset[tuple[str, str]]) -> Iterator[None]:
    """Declare ``routes`` public while the Hunch factory installs request identity.

    A deployment receives this declaration as ``FASTAPI_PUBLIC_INGRESS``, which the SDK reads once,
    at installation. The process value is restored after.
    """
    previous = os.environ.get("FASTAPI_PUBLIC_INGRESS")
    os.environ["FASTAPI_PUBLIC_INGRESS"] = json.dumps(
        [{"method": method, "path": path} for method, path in sorted(routes)]
    )
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("FASTAPI_PUBLIC_INGRESS", None)
        else:
            os.environ["FASTAPI_PUBLIC_INGRESS"] = previous


def _signed_in_authorization() -> bytes:
    """Return this process's SDK sign-in as a Bearer credential (the SDK renews it first)."""
    value = str(get_authorization_headers().get("Authorization") or "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("The SDK sign-in has no Bearer token.")
    return f"Bearer {token.strip()}".encode("latin-1")


def create_app() -> FastAPI:
    # The developer reads this process's output: show warnings and errors of every logger.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if any(os.environ.get(name) for name in ("APP_NAME", "FASTAPI_PUBLIC_BASE_URL")):
        raise RuntimeError(
            "The loopback Hunch launcher runs only outside a Main Sequence deployment."
        )
    with _public_ingress(ANONYMOUS_ROUTES):
        application = create_hunch_app()
    if application.state.mainsequence_request_identity["mode"] != "local":
        raise RuntimeError("The loopback Hunch launcher requires the local request identity mode.")

    @application.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ready"}

    @application.middleware("http")
    async def local_signed_user(request: Request, call_next):
        if not _is_loopback(request):
            return JSONResponse(
                {"detail": "The local Hunch API accepts loopback requests only."}, status_code=403
            )
        headers = [
            (name, value)
            for name, value in request.scope["headers"]
            if name.lower() not in CALLER_HEADERS
        ]
        if (request.method, request.scope["path"]) in ANONYMOUS_ROUTES:
            request.scope["headers"] = [*headers, (b"x-public-ingress", b"1")]
            return await call_next(request)
        if len(headers) != len(request.scope["headers"]):
            return JSONResponse(
                {"detail": "The local Hunch API does not accept caller identity headers."},
                status_code=401,
            )
        try:
            authorization = await asyncio.wait_for(
                asyncio.to_thread(_signed_in_authorization),
                timeout=LOCAL_SIGN_IN_TIMEOUT_SECONDS,
            )
        except AuthenticationError:
            return JSONResponse(
                {
                    "detail": {
                        "code": "identity_unavailable",
                        "message": "Sign in with the SDK CLI.",
                    }
                },
                status_code=503,
            )
        except Exception:
            return JSONResponse(
                {
                    "detail": {
                        "code": "identity_unavailable",
                        "message": "The Main Sequence sign-in could not be verified.",
                    }
                },
                status_code=503,
            )
        # The installed request identity verifies this credential with
        # MAINSEQUENCE_ENDPOINT/api/v1/users/me/, binds that user as the caller and removes the
        # header before any route runs.
        request.scope["headers"] = [*headers, (b"authorization", authorization)]
        return await call_next(request)

    return application


app = create_app()

__all__ = ["app", "create_app"]
