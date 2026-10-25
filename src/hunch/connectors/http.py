"""A small typed HTTP client for the Main Sequence connector applications.

Every connector exposes the same Command Center contracts (collections with ``items`` and
``pageInfo``, errors as ``{"detail": {"code", "message", "retryable"}}``) behind the SDK request
identity. Two transports:

- ``ConnectorHTTPClient(base_url)``: a fixed origin with this process's SDK sign-in (local
  development against a connector running on the same machine).
- ``ReleaseHTTPClient(release_uid)``: the hosted path. The Hunch workload asks the platform for
  runtime access to the connector's ``ResourceRelease`` (``resolve-runtime-access``), which answers
  with the release's RPC URL and a short-lived bearer token for the Hunch workload; calls go to that
  URL with that token, the grant is cached until it nears expiry and renewed once on a 401. This is
  the same mechanism the Tau runtime uses for ``call_release``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

import requests

from hunch.connectors.base import ConnectorCapabilityUnavailable, ConnectorError

HeadersProvider = Callable[[], Mapping[str, str]]
DEFAULT_TIMEOUT = 30.0


def sdk_headers() -> Mapping[str, str]:
    from mainsequence.client.utils import get_authorization_headers

    return dict(get_authorization_headers())


class ConnectorHTTPClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: HeadersProvider | None = None,
        release_uid: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = headers or sdk_headers
        self._release_uid = release_uid
        self._timeout = timeout
        self._session = session or requests.Session()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        timeout: float | None = None,
    ) -> Any:
        headers = {"Accept": "application/json", **self._headers()}
        if self._release_uid:
            headers["X-Resource-Release-UID"] = self._release_uid
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json,
                headers=headers,
                timeout=timeout or self._timeout,
            )
        except requests.RequestException as exc:
            raise ConnectorError(
                f"The connector at {self.base_url} is unreachable ({type(exc).__name__}).",
                code="provider_unavailable",
                retryable=True,
            ) from exc
        if response.status_code == 404:
            detail = _detail(response)
            if detail.get("code") in (None, "not_found") and _looks_like_missing_route(response):
                raise ConnectorCapabilityUnavailable(
                    f"The connector does not offer {method} {path}."
                )
            raise ConnectorError(
                detail.get("message") or "Not found.", code="not_found", retryable=False
            )
        if response.status_code >= 400:
            detail = _detail(response)
            raise ConnectorError(
                detail.get("message") or f"The connector answered {response.status_code}.",
                code=str(detail.get("code") or f"http_{response.status_code}"),
                retryable=bool(detail.get("retryable")) or response.status_code in (502, 503, 504),
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError("The connector answered with a non-JSON body.") from exc

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)


def _detail(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str):
        return {"message": detail}
    return {}


def _looks_like_missing_route(response: requests.Response) -> bool:
    detail = _detail(response)
    return detail.get("message") in (None, "Not Found") and detail.get("code") is None


class ReleaseHTTPClient(ConnectorHTTPClient):
    """Calls a platform ResourceRelease through its runtime-access grant (RPC URL + token)."""

    GRANT_REFRESH_MARGIN_SECONDS = 60.0
    WAKE_WAIT_SECONDS = 120.0

    def __init__(
        self,
        release_uid: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
        resolver: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(
            "https://release.invalid", headers=self._grant_headers, timeout=timeout, session=session
        )
        self.release_uid = release_uid
        self._resolver = resolver or self._resolve_with_sdk
        self._grant: tuple[str, str, float | None] | None = None  # rpc_url, token, expires_at

    # -- grant -------------------------------------------------------------------------------
    def _resolve_with_sdk(self) -> Any:
        from mainsequence.client.models_helpers import ResourceRelease

        release = ResourceRelease.get(pk=self.release_uid)
        return release.wait_for_runtime_access(wait_timeout_seconds=self.WAKE_WAIT_SECONDS)

    def _grant_headers(self) -> Mapping[str, str]:
        rpc_url, token, _ = self._current_grant()
        return {"Authorization": f"Bearer {token}"}

    def _current_grant(self, *, refresh: bool = False) -> tuple[str, str, float | None]:
        import time

        if self._grant is not None and not refresh:
            _, _, expires_at = self._grant
            if expires_at is None or expires_at - time.time() > self.GRANT_REFRESH_MARGIN_SECONDS:
                return self._grant
        try:
            answer = self._resolver()
        except Exception as exc:
            raise ConnectorError(
                f"The platform did not grant access to release {self.release_uid} "
                f"({type(exc).__name__}).",
                code="provider_unavailable",
                retryable=True,
            ) from exc
        grant = getattr(answer, "access", None) or {}
        if isinstance(grant, dict):
            mode, token, rpc_url, expires = (
                grant.get("mode"),
                grant.get("token"),
                grant.get("rpc_url"),
                grant.get("expires_at"),
            )
        else:
            mode, token, rpc_url, expires = (
                getattr(grant, "mode", None),
                getattr(grant, "token", None),
                getattr(grant, "rpc_url", None),
                getattr(grant, "expires_at", None),
            )
        if hasattr(token, "get_secret_value"):
            token = token.get_secret_value()
        if mode != "token" or not token or not rpc_url:
            raise ConnectorError(
                f"Release {self.release_uid} offers no token access to call it.",
                code="dependency_unavailable",
                retryable=False,
            )
        expires_at = None
        if expires is not None:
            expires_at = expires.timestamp() if hasattr(expires, "timestamp") else float(expires)
        self._grant = (str(rpc_url).rstrip("/"), str(token), expires_at)
        self.base_url = self._grant[0]
        return self._grant

    def request(self, method: str, path: str, *, params=None, json=None, timeout=None) -> Any:
        self._current_grant()
        try:
            return super().request(method, path, params=params, json=json, timeout=timeout)
        except ConnectorError as exc:
            if exc.code != "http_401":
                raise
        # The token may have expired early or been revoked: obtain a new one, once.
        self._current_grant(refresh=True)
        return super().request(method, path, params=params, json=json, timeout=timeout)


def connector_url(env_name: str) -> str | None:
    value = os.environ.get(env_name, "").strip()
    return value.rstrip("/") or None


__all__ = ["ConnectorHTTPClient", "ReleaseHTTPClient", "connector_url", "sdk_headers"]
