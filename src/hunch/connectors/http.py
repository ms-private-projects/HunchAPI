"""A small typed HTTP client for the Main Sequence connector applications.

Every connector exposes the same Command Center contracts (collections with ``items`` and
``pageInfo``, errors as ``{"detail": {"code", "message", "retryable"}}``) behind the SDK request
identity. Locally the client presents this process's SDK sign-in; hosted, the platform signs the
Hunch workload (and the requester, when the call is requester-bound) into the caller assertion.
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


def connector_url(env_name: str) -> str | None:
    value = os.environ.get(env_name, "").strip()
    return value.rstrip("/") or None


__all__ = ["ConnectorHTTPClient", "connector_url", "sdk_headers"]
