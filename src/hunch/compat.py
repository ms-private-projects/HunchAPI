"""Compatibility shims for the installed ms-markets release, installed once per process.

Each shim names the upstream behaviour it works around and the releases it was checked against, so
it can be removed when ms-markets or MetaTables fixes it. The three ms-markets shims were
re-checked on 3.0.2 (ADR 0048 names: `msm_portfolios.time_index`, `PortfoliosUpdater`); the SQLite
shims also run in the loopback Markets API (`scripts/local_markets_api.py`, ADR 0006). None changes a contract; they only coerce
arguments or keep a new portfolio's starting point its own.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

_INSTALLED = False


def _coerce_uuid(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return value
    return value


def _patch_calendar_session_search() -> None:
    """ms-markets 2.2.12-3.0.2: `PersistedCalendarSchedule.schedule` passes `calendar_uid` as a str.

    On SQLite the compiled-SQL UUID bind processor expects a `uuid.UUID` and fails with
    `'str' object has no attribute 'hex'`; PostgreSQL accepts both. Coerce before compiling.
    """
    from msm.repositories.calendars import sessions

    original = sessions.build_search_calendar_sessions_operation
    if getattr(original, "_hunch_compat", False):
        return

    def patched(context, *, calendar_uid, **kwargs):
        return original(context, calendar_uid=_coerce_uuid(calendar_uid), **kwargs)

    patched._hunch_compat = True  # type: ignore[attr-defined]
    sessions.build_search_calendar_sessions_operation = patched


def _patch_sqlite_uuid_binds() -> None:
    """ms-markets 2.2.12-3.0.2 passes several UUIDs as strings (`str(row.uid)`) into compiled SQL.

    SQLAlchemy's non-native `Uuid` bind processor, used for SQLite, calls `.hex` on the value and
    fails on a string; PostgreSQL's native UUID accepts both. Coerce UUID strings for SQLite in
    this process only.
    """
    from sqlalchemy.sql import sqltypes

    original = sqltypes.Uuid.bind_processor
    if getattr(original, "_hunch_compat", False):
        return

    def bind_processor(self, dialect):
        processor = original(self, dialect)
        if processor is None or getattr(dialect, "name", "") != "sqlite":
            return processor

        def coerce(value):
            return processor(_coerce_uuid(value))

        return coerce

    bind_processor._hunch_compat = True  # type: ignore[attr-defined]
    sqltypes.Uuid.bind_processor = bind_processor  # type: ignore[method-assign]


def _patch_sqlite_datetime_binds() -> None:
    """ms-markets 3.0.x: the portfolio dataset catalog writes time bounds read back as ISO strings.

    `reconcile` takes ``min``/``max`` of an untyped ``time_index`` column, which SQLite returns as
    text, and writes them into the catalog's DateTime columns; SQLite's DateTime processor accepts
    only ``datetime`` objects and raises ``TypeError``. PostgreSQL accepts the string. Treat an ISO
    string as MetaTables treats a ``datetime`` on SQLite: a UTC timestamp passed through unchanged.
    """
    from sqlalchemy.dialects.sqlite.base import DATETIME

    original = DATETIME.bind_processor
    if getattr(original, "_hunch_compat", False):
        return

    def bind_processor(self, dialect):
        processor = original(self, dialect)

        def coerce(value):
            if isinstance(value, str):
                try:
                    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return processor(value) if processor else value
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt.timezone.utc)
                return parsed.astimezone(dt.timezone.utc)
            return processor(value) if processor else value

        return coerce

    bind_processor._hunch_compat = True  # type: ignore[attr-defined]
    DATETIME.bind_processor = bind_processor  # type: ignore[method-assign]


def _patch_sqlite_expanding_uuid_params() -> None:
    """mainsequence-metatable 0.1.57-0.1.59: expanded ``IN`` parameters skip the SQLite processors.

    ``compile_sqlalchemy_statement`` compiles with ``render_postcompile`` and then runs the SQLite
    bind processors by bind name, but an expanded parameter (``uid_1_1`` of ``uid IN (...)``) has
    no processor under its expanded name, so a ``uuid.UUID`` leaves as its hyphenated string while
    SQLite stores the 32-hex form, and the lookup finds nothing (the Markets API's portfolio
    dataset registration, ``PortfolioTable.uid.in_(...)``). Encode UUIDs as SQLite stores them;
    PostgreSQL operations are untouched.
    """
    from metatables.compiled_sql import v1

    original = v1.build_operation
    if getattr(original, "_hunch_compat", False):
        return

    def _hex(value):
        return value.hex if isinstance(value, uuid.UUID) else value

    def build_operation(*args, **kwargs):
        if kwargs.get("dialect") == "sqlite":
            parameters = kwargs.get("parameters")
            if isinstance(parameters, list):
                kwargs["parameters"] = [_hex(value) for value in parameters]
            elif isinstance(parameters, dict):
                kwargs["parameters"] = {key: _hex(value) for key, value in parameters.items()}
        return original(*args, **kwargs)

    build_operation._hunch_compat = True  # type: ignore[attr-defined]
    v1.build_operation = build_operation


def _patch_portfolio_progress_fallback() -> None:
    """ms-markets 2.2.12-3.0.2: a portfolio's first run starts after the *table's* latest time index.

    The rebalance, weights and values updaters of every portfolio share one storage table. When the
    update statistics carry per-portfolio progress and this portfolio has no entry yet, the updaters
    fall back to `max_time_index_value`, the latest row of any portfolio, so a portfolio created
    after another one skips every event up to that time and never gets a first rebalance. A missing
    entry in a populated progress map means "new portfolio": start from `OFFSET_START`.
    """
    from msm_portfolios.time_index import portfolios as portfolio_updaters
    from msm_portfolios.time_index.portfolios import rebalance, weights

    targets = (
        (rebalance.PortfolioRebalance, "_latest_transition_time_index_value"),
        (weights.PortfolioWeights, "_latest_projection_time_index_value"),
        (portfolio_updaters.PortfoliosUpdater, "_latest_portfolio_time_index_value"),
    )
    for updater_class, method_name in targets:
        original = getattr(updater_class, method_name)
        if getattr(original, "_hunch_compat", False):
            continue

        def patched(self, *, _original=original):
            statistics = getattr(self, "update_statistics", None)
            progress = getattr(statistics, "index_progress", None)
            if isinstance(progress, dict) and progress:
                identifier = (
                    self._portfolio_progress_identifier()
                    if hasattr(self, "_portfolio_progress_identifier")
                    else self._resolve_portfolio_identifier()
                )
                if identifier is not None and identifier not in progress:
                    return None
            return _original(self)

        patched._hunch_compat = True  # type: ignore[attr-defined]
        patched.__name__ = method_name
        setattr(updater_class, method_name, patched)


def install_compat_patches() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _patch_calendar_session_search()
    _patch_sqlite_uuid_binds()
    _patch_sqlite_expanding_uuid_params()
    _patch_sqlite_datetime_binds()
    _patch_portfolio_progress_fallback()
    _INSTALLED = True


__all__ = ["install_compat_patches"]
