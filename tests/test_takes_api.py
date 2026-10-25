"""The takes and profile routes over the verified local caller and the in-memory rows."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.fakes import install_fake_rows

from hunch.api.app.main import create_app
from hunch.profiles import HunchUserProfile
from hunch.takes import Take

THESIS = "Humanoid robots are coming to every home within the decade."


@pytest.fixture
def client(local_caller, monkeypatch) -> TestClient:
    install_fake_rows(monkeypatch, HunchUserProfile, Take)
    return TestClient(create_app(), headers=local_caller.headers)


def test_profile_is_created_on_first_contact_and_editable(client, local_caller) -> None:
    profile = client.get("/v1/profile")
    assert profile.status_code == 200
    body = profile.json()
    assert body["user_uid"] == local_caller.uid
    assert body["handle"] == "operator"
    changed = client.patch("/v1/profile", json={"handle": "Hunch Fan", "display_name": "Fan"})
    assert changed.status_code == 200
    assert changed.json()["handle"] == "hunch_fan"
    bad = client.patch("/v1/profile", json={"handle": "x"})
    assert bad.status_code in (409, 422)


def test_take_lifecycle_through_the_api(client, local_caller) -> None:
    created = client.post(
        "/v1/takes",
        json={
            "title": "Robots at home",
            "thesis_text": THESIS,
            "constraints": {"cash_buffer": 0.1},
        },
    )
    assert created.status_code == 201, created.text
    take = created.json()
    assert take["status"] == "draft" and take["constraints"]["cash_buffer"] == 0.1
    assert take["owner_handle"] == "operator"
    uid = take["uid"]

    listed = client.get("/v1/takes", params={"scope": "mine", "limit": 10})
    assert listed.status_code == 200
    page = listed.json()
    assert page["pageInfo"]["totalItems"] == 1 and page["items"][0]["uid"] == uid

    discovery = client.get("/v1/takes/discovery")
    assert discovery.status_code == 200
    assert discovery.json()["resource"]["id"] == "takes"
    assert client.get("/v1/takes/discovery", params={"limit": 5}).status_code == 409

    too_early = client.post(f"/v1/takes/{uid}/actions/publish")
    assert too_early.status_code == 409
    assert too_early.json()["detail"]["code"] == "action_conflict"

    edited = client.patch(f"/v1/takes/{uid}", json={"title": "Robots everywhere"})
    assert edited.status_code == 200 and edited.json()["title"] == "Robots everywhere"

    mode = client.post(
        f"/v1/takes/{uid}/actions/set-execution-mode", json={"execution_mode": "approval"}
    )
    assert mode.status_code == 200 and mode.json()["execution_mode"] == "approval"

    Take.update(uid, status="built")
    published = client.post(f"/v1/takes/{uid}/actions/publish")
    assert published.status_code == 200 and published.json()["visibility"] == "public"

    other = TestClient(create_app(), headers=local_caller.other_headers)
    public = other.get("/v1/takes", params={"scope": "public"})
    assert public.status_code == 200 and public.json()["pageInfo"]["totalItems"] == 1
    forked = other.post(f"/v1/takes/{uid}/actions/fork")
    assert forked.status_code == 201
    assert forked.json()["forked_from_take_uid"] == uid
    assert forked.json()["owner_user_uid"] == local_caller.other_uid
    assert other.patch(f"/v1/takes/{uid}", json={"title": "Hijack"}).status_code == 404

    refused = client.post(f"/v1/takes/{uid}/actions/archive", json={"confirmation": "DELETE"})
    assert refused.status_code == 409
    archived = client.post(
        f"/v1/takes/{uid}/actions/archive", json={"confirmation": f"DELETE {uid}"}
    )
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert other.get(f"/v1/takes/{uid}").status_code == 404


def test_validation_errors_never_echo_the_input(client) -> None:
    response = client.post("/v1/takes", json={"title": "", "thesis_text": "zebra-probe"})
    assert response.status_code == 422
    assert "zebra-probe" not in response.text
    page = client.get("/v1/takes", params={"limit": 10, "offset": 5})
    assert page.status_code == 409
