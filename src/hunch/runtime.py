"""ms-markets runtime bootstrap for Hunch.

Storage-first ms-markets requires one ``start_engine(...)`` per process **before** any
MetaTable-backed row, repository, service or DataNode operation. It attaches the runtime to the
already-migrated MetaTables; it never creates schema (the migration providers do). A process may
attach only one model set, so every entry point attaches the complete set below.

Call ``start_markets_engine()`` once at every process entry point (each Job ``main()``, FastAPI
startup, the local launcher).
"""

from __future__ import annotations

from typing import Any

ROW_MODEL_NAME = "hunch.runtime"


def project_models() -> list[type[Any]]:
    """Project-owned MetaTables, in dependency order."""
    from hunch.community import project_community_models
    from hunch.funding import project_funding_models
    from hunch.instruments import project_instrument_models
    from hunch.portfolios import project_portfolio_models
    from hunch.profiles import project_profile_models
    from hunch.reviews import project_review_models
    from hunch.takes import project_take_models
    from hunch.takes.revisions import project_revision_models

    return [
        *project_profile_models(),
        *project_instrument_models(),
        *project_take_models(),
        *project_revision_models(),
        *project_portfolio_models(),
        *project_funding_models(),
        *project_review_models(),
        *project_community_models(),
    ]


def application_runtime_models() -> list[type[Any]]:
    """Complete model set every Hunch process attaches.

    The ms-markets portfolio graph (signals, calendar events, rebalances, weights, values,
    external prices), the asset registry and snapshots, accounts with holdings, target positions
    and virtual funds, the execution ledger, and the Hunch tables. ``start_engine`` re-orders by
    foreign-key dependency and auto-includes referenced built-in tables.
    """
    from msm_pricing.data_nodes.pricing_details.storage import AssetPricingDetailsStorage
    from msm_pricing.models.pricing_details import AssetCurrentPricingDetailsTable

    from msm.data_nodes.accounts.storage import AccountHoldingsStorage
    from msm.data_nodes.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
    from msm.data_nodes.assets.storage import AssetSnapshotsStorage
    from msm.data_nodes.execution.storage import (
        OrderEventsStorage,
        OrdersStorage,
        TradesStorage,
    )
    from msm.models import (
        AssetCategoryMembershipTable,
        AssetCategoryTable,
        CalendarDateTable,
        CalendarSessionTable,
        OpenFigiAssetDetailsTable,
        OrderManagerTable,
        VirtualFundHoldingsSetTable,
    )
    from msm.models.assets.bonds import BondAssetDetailsTable
    from msm.models.assets.currency_spot import CurrencySpotAssetDetailsTable
    from msm.models.derivatives import FutureAssetDetailsTable
    from msm.models.index_formulas import IndexFormulaInputTable
    from msm_portfolios.bootstrap import resolve_portfolio_models

    return [
        *resolve_portfolio_models(None),
        # Every registered static table that references the asset table is attached: the governed
        # SQL layer checks them on upserts of the asset key (assets themselves are created with
        # plain inserts, see hunch.instruments.services).
        BondAssetDetailsTable,
        CurrencySpotAssetDetailsTable,
        FutureAssetDetailsTable,
        IndexFormulaInputTable,
        AssetPricingDetailsStorage,
        AssetCurrentPricingDetailsTable,
        OpenFigiAssetDetailsTable,
        AssetSnapshotsStorage,
        AssetCategoryTable,
        AssetCategoryMembershipTable,
        CalendarDateTable,
        CalendarSessionTable,
        AccountHoldingsStorage,
        VirtualFundHoldingsSetTable,
        VirtualFundHoldingsStorage,
        OrderManagerTable,
        OrdersStorage,
        OrderEventsStorage,
        TradesStorage,
        *project_models(),
    ]


def start_markets_engine(
    *,
    timeout: int | float | tuple[float, float] | None = None,
) -> Any:
    """Attach the markets runtime once for this process. Returns the ``MarketsRuntime``.

    Raises if the platform backend is unreachable or a required MetaTable is not migrated yet.
    """
    import msm_portfolios
    from hunch.compat import install_compat_patches
    from msm.bootstrap import resolve_runtime

    install_compat_patches()
    models = application_runtime_models()
    try:
        return resolve_runtime(models=models, row_model_name=ROW_MODEL_NAME)
    except RuntimeError as exc:
        if "requires an initialized markets runtime" not in str(exc):
            raise
    return msm_portfolios.start_engine(models=models, timeout=timeout)


def markets_runtime() -> Any:
    """The attached runtime (after ``start_markets_engine``), for table lookups."""
    from msm.bootstrap import resolve_runtime

    return resolve_runtime(models=application_runtime_models(), row_model_name=ROW_MODEL_NAME)


__all__ = [
    "ROW_MODEL_NAME",
    "application_runtime_models",
    "markets_runtime",
    "project_models",
    "start_markets_engine",
]
