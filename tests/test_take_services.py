"""Take lifecycle rules, exercised against the in-memory row store."""

from __future__ import annotations

import uuid

import pytest
from tests.fakes import install_fake_rows

from hunch.profiles import HunchUserProfile
from hunch.profiles.services import ensure_profile, normalize_handle, update_profile
from hunch.takes import Take
from hunch.takes.services import (
    TakeConstraints,
    TakeCreate,
    TakeStateError,
    TakeUpdate,
    archive_take,
    create_take,
    fork_take,
    get_take_for,
    list_takes,
    publish_take,
    set_execution_mode,
    unpublish_take,
    update_take,
)

ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def rows(monkeypatch):
    return install_fake_rows(monkeypatch, HunchUserProfile, Take)


def _create(owner: str, title: str = "Robots everywhere", **kwargs) -> Take:
    return create_take(
        owner,
        TakeCreate(title=title, thesis_text="Humanoid robots are coming to every home.", **kwargs),
        username=f"{owner[:4]}@example.test",
    )


def test_create_take_makes_a_draft_and_the_owners_profile(rows) -> None:
    take = _create(ALICE)
    assert (take.status, take.execution_mode, take.visibility) == ("draft", "practice", "private")
    assert take.constraints_json == TakeConstraints().model_dump()
    assert take.created_at is not None and take.updated_at is not None
    profile = HunchUserProfile.get_by_uid(ALICE)
    assert profile is not None and profile.handle == "1111"


def test_profile_handles_are_normalised_unique_and_editable(rows) -> None:
    first = ensure_profile(ALICE, username="Jose.Perez@example.test")
    assert first.handle == "jose_perez"
    second = ensure_profile(BOB, username="jose.perez@other.test")
    assert second.handle == "jose_perez_2"
    assert normalize_handle("  My Handle! ") == "my_handle"
    with pytest.raises(ValueError):
        update_profile(BOB, handle="jose_perez")
    changed = update_profile(BOB, handle="bob_builds", display_name=" Bob ")
    assert (changed.handle, changed.display_name) == ("bob_builds", "Bob")
    with pytest.raises(ValueError):
        normalize_handle("ab")


def test_private_takes_are_invisible_to_others_until_published(rows) -> None:
    take = _create(ALICE)
    assert get_take_for(ALICE, take.uid).uid == take.uid
    with pytest.raises(LookupError):
        get_take_for(BOB, take.uid)
    with pytest.raises(TakeStateError):
        publish_take(ALICE, take.uid)
    Take.update(take.uid, status="built")
    published = publish_take(ALICE, take.uid)
    assert published.visibility == "public" and published.published_at is not None
    assert get_take_for(BOB, take.uid).title == take.title
    assert unpublish_take(ALICE, take.uid).visibility == "private"
    with pytest.raises(LookupError):
        get_take_for(BOB, take.uid)


def test_only_the_owner_edits_and_archive_needs_the_exact_confirmation(rows) -> None:
    take = _create(ALICE)
    with pytest.raises(LookupError):
        update_take(BOB, take.uid, TakeUpdate(title="Hijack"))
    edited = update_take(ALICE, take.uid, TakeUpdate(title="Robots at home"))
    assert edited.title == "Robots at home"
    assert set_execution_mode(ALICE, take.uid, "approval").execution_mode == "approval"
    with pytest.raises(ValueError):
        set_execution_mode(ALICE, take.uid, "yolo")
    with pytest.raises(ValueError):
        archive_take(ALICE, take.uid, "DELETE")
    archived = archive_take(ALICE, take.uid, f"DELETE {take.uid}")
    assert (archived.status, archived.visibility) == ("archived", "private")
    with pytest.raises(TakeStateError):
        update_take(ALICE, take.uid, TakeUpdate(title="Too late"))


def test_fork_copies_the_take_and_keeps_lineage(rows) -> None:
    source = _create(ALICE)
    with pytest.raises(LookupError):
        fork_take(BOB, source.uid)
    Take.update(source.uid, status="built")
    publish_take(ALICE, source.uid)
    fork = fork_take(BOB, source.uid, username="bob@example.test")
    assert fork.owner_user_uid == BOB
    assert (fork.status, fork.visibility, fork.execution_mode) == ("draft", "private", "practice")
    assert fork.forked_from_take_uid == source.uid and fork.origin_take_uid == source.uid
    Take.update(fork.uid, status="built")
    publish_take(BOB, fork.uid)
    second = fork_take(ALICE, fork.uid)
    assert second.forked_from_take_uid == fork.uid and second.origin_take_uid == source.uid


def test_lists_are_scoped_searchable_and_paginated(rows) -> None:
    mine = [_create(ALICE, title=f"Mine {index}") for index in range(3)]
    # Creation timestamps are whole seconds; make them distinct so "newest first" is testable.
    for index, row in enumerate(mine):
        Take.update(row.uid, created_at=row.created_at.replace(second=index))
    theirs = _create(BOB, title="Theirs public")
    Take.update(theirs.uid, status="built")
    publish_take(BOB, theirs.uid)
    hidden = _create(BOB, title="Theirs private")
    assert hidden.visibility == "private"

    page, total = list_takes(ALICE, scope="mine", limit=2, offset=0)
    assert total == 3 and [row.title for row in page] == ["Mine 2", "Mine 1"]
    page, total = list_takes(ALICE, scope="mine", limit=2, offset=2)
    assert total == 3 and [row.title for row in page] == ["Mine 0"]

    public, total = list_takes(ALICE, scope="public")
    assert total == 1 and public[0].uid == theirs.uid

    found, total = list_takes(ALICE, scope="mine", search="mine 1")
    assert total == 1 and found[0].uid == mine[1].uid
    with pytest.raises(ValueError):
        list_takes(ALICE, status="unknown")
    assert list_takes(ALICE, status="draft")[1] == 3
    assert uuid.UUID(str(mine[0].uid))
