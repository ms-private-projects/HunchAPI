"""The Hunch API authenticates every caller through the SDK request identity."""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from hunch.api.app.main import ROUTERS, create_app
from mainsequence.server.caller_assertions import CallerAssertionUnavailable

HOSTED_MARKERS = (
    "APP_NAME",
    "FASTAPI_PUBLIC_BASE_URL",
    "MAINSEQUENCE_CALLER_ASSERTION_ISSUER",
    "MAINSEQUENCE_CALLER_ASSERTION_JWKS_URL",
)


def launcher_check(app: FastAPI, *, public_ingress: tuple[tuple[str, str], ...]) -> None:
    """The check the platform's FastAPI launcher runs before it serves an application."""
    declaration = getattr(app.state, "mainsequence_request_identity", None)
    if not isinstance(declaration, dict) or declaration.get("installed") is not True:
        raise RuntimeError("Application request identity is not installed.")
    hosted = any(os.environ.get(name) for name in HOSTED_MARKERS)
    expected_mode = os.environ.get("MAINSEQUENCE_CALLER_AUTH_MODE") or (
        "assertion" if hosted else "local"
    )
    if declaration.get("mode") != expected_mode:
        raise RuntimeError("Application caller authentication mode conflicts with deployment.")
    if declaration.get("public_ingress") != tuple(public_ingress):
        raise RuntimeError("Application caller public-ingress policy conflicts with deployment.")


def anonymous_requests() -> list[tuple[str, str]]:
    """One request per method of every declared route, with placeholder path parameters.

    The routes are read from the routers `create_app` mounts: after `install_mcp` the application
    no longer enumerates them through `app.routes`.
    """
    return [
        (
            method,
            route.path_format.format(
                **{name: str(uuid.uuid4()) for name in route.param_convertors}
            ),
        )
        for router in ROUTERS
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods or ())
    ]


def test_local_launch_declares_local_request_identity(clean_identity_environment) -> None:
    app = create_app()
    assert app.state.mainsequence_request_identity == {
        "installed": True,
        "mode": "local",
        "public_ingress": (),
    }
    launcher_check(app, public_ingress=())


def test_hosted_deployment_declares_assertion_request_identity(hosted_caller) -> None:
    app = create_app()
    assert app.state.mainsequence_request_identity == {
        "installed": True,
        "mode": "assertion",
        "public_ingress": (),
    }
    launcher_check(app, public_ingress=())


def test_every_route_rejects_an_anonymous_request(local_caller) -> None:
    client = TestClient(create_app())
    requests = anonymous_requests()
    assert ("GET", "/health") in requests
    for method, path in requests:
        response = client.request(method, path)
        assert response.status_code == 401, (method, path, response.text)
    assert client.post("/mcp", json={}).status_code == 401


def test_health_and_project_state_answer_a_verified_local_caller(api_client, local_caller) -> None:
    assert api_client.get("/health").json() == {"status": "ok"}
    capabilities = api_client.get("/v1/project-state/capabilities")
    assert capabilities.status_code == 200
    assert {item["key"] for item in capabilities.json()["capabilities"]} >= {
        "project_state",
        "takes",
        "portfolios",
        "profiles",
    }
    with patch("hunch.api.app.services.project_state.resolve_site_agent", return_value=None):
        configuration = api_client.get("/v1/project-state/configuration")
    assert configuration.status_code == 200
    body = configuration.json()
    assert body["request_user_uid"] == local_caller.uid
    assert body["venues"] == ["alpaca", "ibkr"]
    assert body["agent_uid"] is None
    assert body["disclaimers"]


def test_hosted_caller_assertion_is_verified_and_a_forgery_is_refused(hosted_caller) -> None:
    client = TestClient(create_app())
    assert client.get("/health", headers=hosted_caller.headers()).status_code == 200
    forged = {"X-MainSequence-Caller-Assertion": hosted_caller.forge()}
    assert client.get("/health", headers=forged).status_code == 401


@pytest.mark.parametrize("marker", HOSTED_MARKERS)
def test_a_deployment_marker_without_the_verifier_configuration_refuses_to_build(
    clean_identity_environment, monkeypatch, marker
) -> None:
    """A hosted process must carry the platform's complete caller-assertion configuration."""
    monkeypatch.setenv(marker, "set")
    with pytest.raises(CallerAssertionUnavailable):
        create_app()
