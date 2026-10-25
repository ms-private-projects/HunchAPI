"""ms-markets runtime bootstrap for Hunch.

Storage-first ms-markets requires one ``msm.start_engine(...)`` per process **before** any
MetaTable-backed row, repository, service or DataNode operation. It attaches the runtime to the
already-migrated MetaTables; it never creates schema (the migration providers do). It is
idempotent and cached per configuration, so calling ``start_markets_engine()`` more than once in a
process is safe.

Call it once at every process entry point (each Job ``main()``, FastAPI startup).
"""

from __future__ import annotations

from typing import Any

ROW_MODEL_NAME = "hunch.runtime"


def project_runtime_models() -> list[type[Any]]:
    """MetaTable models Hunch attaches at runtime, in rough dependency order.

    The ms-markets identity tables Hunch rows reference (accounts, calendars, indices, signals,
    portfolios) plus the project-owned tables. ``msm.start_engine`` re-orders by foreign-key
    dependency and auto-includes referenced built-in tables.
    """
    from hunch.portfolios import project_portfolio_models
    from hunch.profiles import project_profile_models
    from hunch.takes import project_take_models
    from msm.models import (
        AccountGroupTable,
        AccountTable,
        CalendarTable,
        IndexTable,
        IndexTypeTable,
        PortfolioTable,
    )
    from msm_portfolios.models import PortfolioMetadataTable, SignalMetadataTable

    return [
        AccountGroupTable,
        AccountTable,
        CalendarTable,
        IndexTypeTable,
        IndexTable,
        SignalMetadataTable,
        PortfolioTable,
        PortfolioMetadataTable,
        *project_profile_models(),
        *project_take_models(),
        *project_portfolio_models(),
    ]


def application_runtime_models() -> list[type[Any]]:
    """Complete model set used by the API process and shared services."""
    return project_runtime_models()


def start_markets_engine(
    *,
    models: list[type[Any]] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> Any:
    """Attach the markets runtime once for this process. Returns the ``MarketsRuntime``.

    Raises if the platform backend is unreachable or a required MetaTable is not migrated yet.
    """
    import msm
    from msm.bootstrap import resolve_runtime

    resolved_models = models if models is not None else application_runtime_models()
    try:
        return resolve_runtime(models=resolved_models, row_model_name=ROW_MODEL_NAME)
    except RuntimeError as exc:
        if "requires an initialized markets runtime" not in str(exc):
            raise
    return msm.start_engine(models=resolved_models, timeout=timeout)


__all__ = [
    "ROW_MODEL_NAME",
    "application_runtime_models",
    "project_runtime_models",
    "start_markets_engine",
]
