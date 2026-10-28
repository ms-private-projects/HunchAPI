"""Hunch's side of the Markets API boundary (ADR 0006): its own namespace, its own series."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hunch.migrations import METADATA, PROJECT_TABLE_NAMES, all_project_metatable_models
from hunch.runtime import (
    MARKETS_API_WAKE_SECONDS,
    application_runtime_models,
    markets_api_client,
    project_models,
)
from hunch.series import project_series_models


def test_every_hunch_table_is_catalogued_in_the_hunch_namespace() -> None:
    for model in application_runtime_models():
        table = model.__table__
        assert table.info["namespace"] == "hunch", table.name
        assert table.name.startswith("hunch__"), table.name
        assert str(table.info["identifier"]).startswith("hunch."), table.name


def test_the_runtime_attaches_only_hunch_tables() -> None:
    names = {model.__table__.name for model in application_runtime_models()}
    assert names == PROJECT_TABLE_NAMES
    assert {m.__table__.name for m in project_series_models()} <= names


def test_series_instances_keep_their_contract_and_fit_postgresql_names() -> None:
    for model in project_series_models():
        table = model.__table__
        assert len(table.name) <= 63, table.name
        assert any(fk.column.table.name.startswith("ms_markets__") for fk in table.foreign_keys)


def test_markets_tables_appear_only_as_key_only_references() -> None:
    references = {
        name: table for name, table in METADATA.tables.items() if name not in PROJECT_TABLE_NAMES
    }
    assert references, "the project tables reference Markets registries"
    for name, table in references.items():
        assert name.startswith("ms_markets__"), name
        assert not table.foreign_keys, name
        assert set(table.c.keys()) <= {"uid", "unique_identifier", "signal_uid"}, name


def test_the_markets_client_waits_for_a_waking_markets_api(monkeypatch) -> None:
    from msm.client import discovery

    waits: list[float] = []

    def resolve(*, timeout):
        waits.append(timeout)
        return discovery.MarketsApiEndpoint(
            "https://markets.example.test", release_uid=None, headers=lambda _force: {}
        )

    monkeypatch.setattr(discovery, "resolve_markets_api_endpoint", resolve)
    client = markets_api_client()
    assert (
        waits == [MARKETS_API_WAKE_SECONDS]
        and MARKETS_API_WAKE_SECONDS > discovery.DISCOVERY_TIMEOUT
    )
    assert client.base_url == "https://markets.example.test"


def test_hunch_row_classes_require_only_hunch_tables() -> None:
    import hunch.community as community
    import hunch.funding as funding
    import hunch.instruments as instruments
    import hunch.portfolios as portfolios
    import hunch.profiles as profiles
    import hunch.reviews as reviews
    import hunch.takes as takes
    import hunch.takes.revisions as revisions

    hunch_tables = set(project_models())
    for module in (
        community,
        funding,
        instruments,
        portfolios,
        profiles,
        reviews,
        takes,
        revisions,
    ):
        for value in vars(module).values():
            required = getattr(value, "__required_tables__", None)
            if isinstance(value, type) and required and value.__module__ == module.__name__:
                assert set(required) <= hunch_tables, value.__name__


class _FakeMetaTable:
    patched: list[tuple[str, dict]] = []
    rows: dict[str, list[SimpleNamespace]] = {}

    @classmethod
    def filter(cls, *, physical_table_name: str):
        return cls.rows.get(physical_table_name, [])

    @classmethod
    def patch_by_uid(cls, uid: str, **values):
        cls.patched.append((uid, values))


def test_namespace_move_re_homes_only_this_providers_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metatables
    from hunch.migrations.namespace_move import move_project_tables_to_namespace

    profile = all_project_metatable_models()[0].__table__
    _FakeMetaTable.patched = []
    _FakeMetaTable.rows = {
        profile.name: [
            SimpleNamespace(
                uid="u-1",
                namespace="mainsequence.markets",
                identifier="HunchUserProfile",
                migration_provider_key="hunch:hunch",
                migration_namespace="hunch",
            ),
            SimpleNamespace(
                uid="u-2",
                namespace="mainsequence.markets",
                identifier="Other",
                migration_provider_key="other:other",
                migration_namespace="other",
            ),
        ]
    }
    monkeypatch.setattr(metatables, "MetaTable", _FakeMetaTable)

    planned = move_project_tables_to_namespace(dry_run=True)
    assert [item["physical_table_name"] for item in planned] == [profile.name]
    assert _FakeMetaTable.patched == []

    move_project_tables_to_namespace()
    assert _FakeMetaTable.patched == [
        ("u-1", {"identifier": profile.info["identifier"], "namespace": "hunch"})
    ]
