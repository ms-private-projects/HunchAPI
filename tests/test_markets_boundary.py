"""Hunch's side of the Markets API boundary (ADR 0006): its own namespace, its own series."""

from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from hunch import runtime
from hunch.migrations import METADATA, PROJECT_TABLE_NAMES, all_project_metatable_models
from hunch.runtime import (
    MARKETS_API_REQUEST_SECONDS,
    MARKETS_API_WAKE_SECONDS,
    METATABLES_API_WAKE_SECONDS,
    application_runtime_models,
    markets_api_client,
    project_models,
    wait_for_metatables_api,
    wake_markets_api,
)
from hunch.series import project_series_models

BUILD_LAUNCHER = Path(__file__).resolve().parents[1] / "src/jobs/run_hunch_take_build.py"


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
    assert client.timeout == MARKETS_API_REQUEST_SECONDS


@pytest.fixture
def no_remote_backend(monkeypatch):
    """No Markets backend selected yet; the process's selection is restored afterwards."""
    from msm.api import remote

    monkeypatch.setattr(remote, "_remote_backend", None)
    monkeypatch.delenv(remote.MSM_API_BACKEND_ENV, raising=False)
    return remote


def test_the_markets_api_wakes_in_the_background_and_the_first_call_waits_for_it(
    monkeypatch, no_remote_backend
) -> None:
    waking = threading.Event()
    released = threading.Event()
    resolved_on: list[str] = []
    client = object()

    def resolve():
        resolved_on.append(threading.current_thread().name)
        waking.set()
        released.wait(5)
        return client

    monkeypatch.setattr(runtime, "markets_api_client", resolve)
    thread = wake_markets_api()
    assert thread is not None and thread.daemon
    assert waking.wait(5)

    backend = no_remote_backend.active_remote_backend()
    first_call: list[object] = []
    caller = threading.Thread(target=lambda: first_call.append(backend.client))
    caller.start()
    caller.join(0.2)
    assert caller.is_alive() and not first_call  # the first call waits for the wake

    released.set()
    thread.join(5)
    caller.join(5)
    assert first_call == [client]
    assert resolved_on == ["markets-api-wake"]  # resolved once, by the wake


def test_a_failed_wake_leaves_the_first_call_to_resolve_again(
    monkeypatch, no_remote_backend, caplog
) -> None:
    client = object()
    attempts: list[int] = []

    def resolve():
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError("still waking: secret-detail")
        return client

    monkeypatch.setattr(runtime, "markets_api_client", resolve)
    with caplog.at_level(logging.WARNING, logger="hunch.runtime"):
        thread = wake_markets_api()
        assert thread is not None
        thread.join(5)
    assert "Waking the Markets API failed: TimeoutError" in caplog.text
    assert "secret-detail" not in caplog.text
    assert no_remote_backend.active_remote_backend().client is client
    assert len(attempts) == 2


def test_no_wake_without_the_lazy_markets_backend(no_remote_backend) -> None:
    no_remote_backend.use_remote_backend(SimpleNamespace(call=lambda *_: None))
    assert wake_markets_api() is None


def test_the_build_job_wakes_the_markets_api_before_attaching_the_runtime(monkeypatch) -> None:
    from hunch.migrations import schema_gate
    from hunch.portfolios import build

    spec = importlib.util.spec_from_file_location("run_hunch_take_build", BUILD_LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(launcher)

    steps: list[str] = []
    monkeypatch.setattr(schema_gate, "skip_if_schema_behind", lambda _name: steps.append("gate"))
    monkeypatch.setattr(runtime, "wake_markets_api", lambda: steps.append("wake"))
    monkeypatch.setattr(runtime, "start_markets_engine", lambda: steps.append("attach"))

    def stop(*_args, **_kwargs):
        steps.append("build")
        raise RuntimeError("stop here")

    monkeypatch.setattr(build, "build_take", stop)
    assert launcher.main(["--take-uid", "be2946ac-0000-0000-0000-000000000000"]) == 1
    assert steps == ["gate", "wake", "attach", "build"]


def test_the_metatables_api_is_resolved_with_a_wake_budget(monkeypatch) -> None:
    from metatables import endpoint

    budgets: list[float] = []
    monkeypatch.setattr(
        endpoint, "resolve_api_endpoint", lambda: budgets.append(endpoint.discovery_budget())
    )
    wait_for_metatables_api()
    assert budgets == [METATABLES_API_WAKE_SECONDS]
    assert METATABLES_API_WAKE_SECONDS > endpoint.DISCOVERY_TIMEOUT
    assert endpoint.discovery_budget() == endpoint.DISCOVERY_TIMEOUT


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
