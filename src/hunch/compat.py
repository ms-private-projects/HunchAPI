"""Compatibility shims for the installed ms-markets release, installed once per process.

Each shim names the upstream behaviour it works around so it can be removed when ms-markets fixes
it. None changes a contract; they only coerce arguments.
"""

from __future__ import annotations

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
    """ms-markets 2.2.12: `PersistedCalendarSchedule.schedule` passes `calendar_uid` as a string.

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
    """ms-markets 2.2.12 passes several UUIDs as strings (`str(row.uid)`) into compiled SQL.

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


def _patch_portfolio_progress_fallback() -> None:
    """ms-markets 2.2.12: a portfolio's first run starts after the *table's* latest time index.

    The rebalance, weights and values nodes of every portfolio share one storage table. When the
    update statistics carry per-portfolio progress and this portfolio has no entry yet, the nodes
    fall back to `max_time_index_value`, the latest row of any portfolio, so a portfolio created
    after another one skips every event up to that time and never gets a first rebalance. A missing
    entry in a populated progress map means "new portfolio": start from `OFFSET_START`.
    """
    from msm_portfolios.data_nodes import portfolios as portfolio_nodes
    from msm_portfolios.data_nodes.portfolios import rebalance, weights

    targets = (
        (rebalance.PortfolioRebalance, "_latest_transition_time_index_value"),
        (weights.PortfolioWeights, "_latest_projection_time_index_value"),
        (portfolio_nodes.PortfoliosDataNode, "_latest_portfolio_time_index_value"),
    )
    for node_class, method_name in targets:
        original = getattr(node_class, method_name)
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
        setattr(node_class, method_name, patched)


def install_compat_patches() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _patch_calendar_session_search()
    _patch_sqlite_uuid_binds()
    _patch_portfolio_progress_fallback()
    _INSTALLED = True


__all__ = ["install_compat_patches"]
