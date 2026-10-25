"""The email digest is composed from undelivered notifications and delivered once."""

from __future__ import annotations

import datetime as dt
import uuid
from email import message_from_bytes

import pytest
from tests.fakes import install_fake_rows

from hunch.channels.delivery import send_digest_for
from hunch.channels.digest import compose_digest, mark_delivered, undelivered
from hunch.channels.email import OutboundEmail, OutboxSender
from hunch.community import HunchNotification
from hunch.community.notifications import notify
from hunch.funding import HunchRebalanceProposal
from hunch.profiles import HunchUserProfile
from hunch.takes import Take

ALICE = "11111111-1111-4111-8111-111111111111"
NOW = dt.datetime(2026, 10, 25, 13, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def rows(monkeypatch):
    return install_fake_rows(
        monkeypatch, HunchUserProfile, Take, HunchNotification, HunchRebalanceProposal
    )


def _setup(email_digest: bool = True):
    profile = HunchUserProfile.create(
        user_uid=ALICE,
        handle="alice",
        display_name="Alice",
        metadata_json={"email_digest": email_digest, "email_address": "alice@example.test"},
    )
    take = Take.create(
        owner_user_uid=ALICE, title="Robots", thesis_text="x", status="active_funded"
    )
    notify(
        ALICE,
        "review_hold",
        "Robots: holding steady",
        body_md="## Daily review\n\n- Verdict: **hold**\n",
        take_uid=take.uid,
        created_at=NOW,
    )
    notify(
        ALICE,
        "proposal_executed",
        "Robots: 3 orders filled",
        take_uid=take.uid,
        created_at=NOW - dt.timedelta(hours=1),
    )
    HunchRebalanceProposal.create(
        take_uid=take.uid,
        funding_uid=uuid.uuid4(),
        owner_user_uid=ALICE,
        trigger="drift",
        status="proposed",
        legs_json=[{"estimated_notional": 1200.0}, {"estimated_notional": 800.0}],
        expires_at=NOW + dt.timedelta(days=1),
        created_at=NOW,
    )
    return profile, take


def test_digest_groups_by_take_and_lists_pending_proposals(rows) -> None:
    profile, take = _setup()
    digest = compose_digest(profile, site_url="https://hunch.test", today=NOW.date())
    assert digest.subject == "Hunch: 1 proposal waiting"
    assert "## 1 proposal waiting for you" in digest.body_md
    assert "about 2,000 estimated" in digest.body_md
    assert "## Robots" in digest.body_md and "- Verdict: **hold**" in digest.body_md
    assert f"https://hunch.test/takes/{take.uid}" in digest.body_md
    assert len(digest.notification_uids) == 2 and not digest.empty
    assert "not a registered investment adviser" in digest.body_md


def test_outbox_sender_writes_a_parsable_eml(tmp_path) -> None:
    receipt = OutboxSender(tmp_path).send(
        OutboundEmail(to="a@example.test", subject="Hi", body_md="Body")
    )
    files = list(tmp_path.glob("*.eml"))
    assert len(files) == 1 and receipt.detail == str(files[0])
    parsed = message_from_bytes(files[0].read_bytes())
    assert parsed["To"] == "a@example.test" and parsed["Subject"] == "Hi"
    assert parsed["Message-ID"] == receipt.message_id


def test_delivery_marks_notifications_and_never_repeats(rows, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HUNCH_EMAIL_SENDER", "outbox")
    monkeypatch.setenv("HUNCH_EMAIL_OUTBOX_DIR", str(tmp_path))
    profile, _ = _setup()
    first = send_digest_for(profile, site_url="https://hunch.test")
    assert (
        first["state"] == "sent"
        and first["to"] == "alice@example.test"
        and first["notifications"] == 2
    )
    assert undelivered(ALICE) == []
    # Pending proposals keep the digest non-empty; delivered notifications are not repeated.
    again = send_digest_for(profile, dry_run=True)
    assert again["state"] == "dry_run" and again["notifications"] == 0
    assert len(list(tmp_path.glob("*.eml"))) == 1


def test_opted_out_and_missing_address_are_reported(rows, monkeypatch) -> None:
    profile, _ = _setup(email_digest=False)
    assert send_digest_for(profile)["state"] == "opted_out"
    HunchUserProfile.update(ALICE, metadata_json={"email_digest": True})
    monkeypatch.setattr("hunch.channels.delivery.platform_email", lambda uid: None)
    assert send_digest_for(HunchUserProfile.get_by_uid(ALICE))["state"] == "no_address"
    mark_delivered([])


def test_platform_sender_uses_a_notification_with_email() -> None:
    from types import SimpleNamespace

    from hunch.channels.email import PlatformNotificationSender

    calls = []

    class FakeNotification:
        @staticmethod
        def send(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(uid="n-1")

    receipt = PlatformNotificationSender(FakeNotification).send(
        OutboundEmail(to="a@example.test", subject="Hi", body_md="Body", user_uid="user-1")
    )
    assert receipt.sender == "platform" and receipt.detail == "n-1"
    assert calls[0]["include_email"] is True and calls[0]["target_user_uid"] == "user-1"
    assert calls[0]["title"] == "Hi" and calls[0]["description"] == "Body"
    with pytest.raises(ValueError):
        PlatformNotificationSender(FakeNotification).send(
            OutboundEmail(to="x", subject="s", body_md="b")
        )


def test_profile_email_preferences_over_rest(local_caller, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from hunch.api.app.main import create_app

    install_fake_rows(monkeypatch, HunchUserProfile)
    client = TestClient(create_app(), headers=local_caller.headers)
    assert client.get("/v1/profile").json()["email_digest"] is False
    updated = client.patch(
        "/v1/profile", json={"email_digest": True, "email_address": "me@example.test"}
    )
    assert updated.status_code == 200 and updated.json()["email_digest"] is True
    assert updated.json()["email_address"] == "me@example.test"
    bad = client.patch("/v1/profile", json={"email_address": "not an address"})
    assert bad.status_code == 409
    cleared = client.patch("/v1/profile", json={"email_address": ""})
    assert cleared.json()["email_address"] is None and cleared.json()["email_digest"] is True
