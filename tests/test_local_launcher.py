"""The loopback launcher presents the developer's sign-in and admits loopback callers only."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_launcher_serves_healthz_anonymously_and_signs_loopback_requests(local_caller) -> None:
    from api.app import local

    app = local.create_app()
    assert app.state.mainsequence_request_identity["public_ingress"] == (("GET", "/healthz"),)
    loopback = TestClient(app, client=("127.0.0.1", 50000))
    assert loopback.get("/healthz").json() == {"status": "ready"}
    with patch.object(
        local, "_signed_in_authorization", return_value=b"Bearer local-session-token"
    ):
        assert loopback.get("/health").json() == {"status": "ok"}
        with patch("hunch.api.app.services.project_state.resolve_site_agent", return_value=None):
            configuration = loopback.get("/v1/project-state/configuration").json()
    assert configuration["request_user_uid"] == local_caller.uid
    # A caller cannot present its own identity to the launcher.
    refused = loopback.get("/health", headers={"Authorization": "Bearer forged"})
    assert refused.status_code == 401
    # Nothing but loopback is served.
    remote = TestClient(app, client=("10.0.0.7", 50000))
    assert remote.get("/health").status_code == 403


def test_launcher_refuses_a_hosted_process(hosted_caller) -> None:
    import importlib

    import pytest
    from api.app import local

    with pytest.raises(RuntimeError):
        importlib.reload(local)
