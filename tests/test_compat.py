"""The ms-markets compatibility shims change only what they say they change."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from hunch.compat import install_compat_patches
from msm_portfolios.time_index import portfolios as portfolio_updaters
from msm_portfolios.time_index.portfolios import rebalance, weights

LATEST = dt.datetime(2026, 10, 23, 20, 0, tzinfo=dt.timezone.utc)


def _statistics(progress: dict | None) -> SimpleNamespace:
    return SimpleNamespace(index_progress=progress, max_time_index_value=LATEST)


def test_a_new_portfolio_starts_from_offset_start_when_others_filled_the_table() -> None:
    install_compat_patches()
    cases = (
        (rebalance.PortfolioRebalance, "_latest_transition_time_index_value"),
        (weights.PortfolioWeights, "_latest_projection_time_index_value"),
        (portfolio_updaters.PortfoliosUpdater, "_latest_portfolio_time_index_value"),
    )
    for updater_class, method_name in cases:
        method = getattr(updater_class, method_name)
        assert getattr(method, "_hunch_compat", False), (updater_class, method_name)
        node = SimpleNamespace(
            _resolve_portfolio_identifier=lambda: "HUNCH_PORTFOLIO__new",
            _portfolio_progress_identifier=lambda: "HUNCH_PORTFOLIO__new",
            _max_in_nested_values=lambda value: max(value.values()),
        )
        # Another portfolio's progress must not become this portfolio's starting point.
        node.update_statistics = _statistics({"HUNCH_PORTFOLIO__other": {"x": LATEST}})
        assert method(node) is None, (updater_class, method_name)
        # This portfolio's own progress still counts.
        node.update_statistics = _statistics({"HUNCH_PORTFOLIO__new": LATEST})
        assert method(node) == LATEST, (updater_class, method_name)
        # Without per-portfolio progress the upstream fallback stays in place.
        node.update_statistics = _statistics(None)
        assert method(node) == LATEST, (updater_class, method_name)


def test_installing_twice_does_not_stack_the_shims() -> None:
    install_compat_patches()
    first = rebalance.PortfolioRebalance._latest_transition_time_index_value
    install_compat_patches()
    assert rebalance.PortfolioRebalance._latest_transition_time_index_value is first


def test_sqlite_operations_carry_uuids_as_sqlite_stores_them(monkeypatch) -> None:
    import uuid

    from hunch import compat
    from metatables.compiled_sql import v1

    calls: list[dict] = []

    def recorder(**kwargs):
        calls.append(kwargs)
        return kwargs

    monkeypatch.setattr(v1, "build_operation", recorder)
    compat._patch_sqlite_expanding_uuid_params()
    value = uuid.UUID("d1f32172-b0a4-481a-a9c4-096b8e445e1a")

    v1.build_operation(dialect="sqlite", parameters=[value, "x"])
    v1.build_operation(dialect="sqlite", parameters={"uid_1_1": value})
    v1.build_operation(dialect="postgresql", parameters=[value])

    assert calls[0]["parameters"] == [value.hex, "x"]
    assert calls[1]["parameters"] == {"uid_1_1": value.hex}
    assert calls[2]["parameters"] == [value]


def test_sqlite_datetime_binds_accept_iso_strings_as_utc_timestamps() -> None:
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.dialects.sqlite.base import DATETIME

    install_compat_patches()
    process = DATETIME().bind_processor(sqlite.dialect())
    assert process("2026-10-27T20:00:00Z") == dt.datetime(2026, 10, 27, 20, tzinfo=dt.timezone.utc)
    assert process("2026-10-27T22:00:00+02:00") == dt.datetime(
        2026, 10, 27, 20, tzinfo=dt.timezone.utc
    )
    stamp = dt.datetime(2026, 10, 27, 20, 0, 0)
    assert process(stamp) == "2026-10-27 20:00:00.000000"


def test_json_lists_reach_postgresql_as_json() -> None:
    import uuid

    import sqlalchemy as sa
    from psycopg.types.json import Jsonb

    from metatables.api.backend.backends.restricted_sql import parameters_for
    from metatables.compiled_sql import v1

    install_compat_patches()
    table = sa.Table(
        "instruments",
        sa.MetaData(),
        sa.Column("figi", sa.String, primary_key=True),
        sa.Column("themes_json", sa.JSON),
        sa.Column("metadata_json", sa.JSON),
    )
    values = {
        "figi": "BBG000B9XRY4",
        "themes_json": ["consumer-devices"],
        "metadata_json": {"a": 1},
    }
    statement = v1.dialect_upsert(table, values, key_columns=["figi"], dialect="postgresql")
    compiled = v1.compile_sqlalchemy_statement(
        statement, operation="upsert", data_source_uid=str(uuid.uuid4()), dialect="postgresql"
    ).statement

    assert compiled.parameter_types == {"themes_json": "json", "metadata_json": "json"}
    bound = parameters_for(compiled.parameters, compiled.parameter_types, "postgresql")
    assert isinstance(bound["themes_json"], Jsonb) and bound["themes_json"].obj == [
        "consumer-devices"
    ]
    assert bound["figi"] == "BBG000B9XRY4"
