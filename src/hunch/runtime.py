"""ms-markets runtime bootstrap for Hunch (the Markets API boundary, ADR 0006).

Every Hunch process reaches the Markets registries (assets, calendars, accounts, portfolios,
signals, funds, order batches) through the Markets API: ``start_markets_engine`` selects the remote
row backend, which serves every row class whose table is catalogued in the Markets namespace. The
process attaches only Hunch's own tables, the product tables and the time-series instances in
``hunch.series``, all catalogued in the ``hunch`` namespace; a Markets table that one of them
references is resolved by physical name and never attached, so Hunch holds no grant on
``mainsequence.markets``.

The Markets API is discovered from the workflow's ``MainSequenceMarkets`` branch grant; locally
``MARKETS_API_URL`` points at the loopback Markets API (``scripts/dev_stack.sh``). The hosted
MetaTables and Markets APIs scale to zero, so the first call of a process waits up to 600 s for
each to wake (the clients' own discovery waits 30 s; cold starts took minutes in development), and
a Markets call may take ``MARKETS_API_REQUEST_SECONDS`` (an 85 s snapshot publish outlived the
client's 60 s default and was reported failed after it had been written).

Call ``start_markets_engine()`` once at every process entry point (each Job ``main()``, FastAPI
startup, the local launcher).
"""

from __future__ import annotations

from typing import Any

ROW_MODEL_NAME = "hunch.runtime"
MARKETS_API_WAKE_SECONDS = 600.0
MARKETS_API_REQUEST_SECONDS = 300.0
METATABLES_API_WAKE_SECONDS = 600.0


def project_models() -> list[type[Any]]:
    """Project-owned MetaTables, in dependency order."""
    from hunch.community import project_community_models
    from hunch.funding import project_funding_models
    from hunch.instruments import project_instrument_models
    from hunch.portfolios import project_portfolio_models
    from hunch.profiles import project_profile_models
    from hunch.reviews import project_review_models
    from hunch.takes import project_take_models
    from hunch.takes.research import project_research_models
    from hunch.takes.revisions import project_revision_models

    return [
        *project_profile_models(),
        *project_instrument_models(),
        *project_take_models(),
        *project_research_models(),
        *project_revision_models(),
        *project_portfolio_models(),
        *project_funding_models(),
        *project_review_models(),
        *project_community_models(),
    ]


def application_runtime_models() -> list[type[Any]]:
    """Every table a Hunch process attaches: the product tables and Hunch's series instances."""
    from hunch.series import project_series_models

    return [*project_models(), *project_series_models()]


def markets_api_client() -> Any:
    """A client for this Environment's Markets API, waiting for a scaled-to-zero API to wake."""
    from msm.client import MarketsClient
    from msm.client.discovery import resolve_markets_api_endpoint

    endpoint = resolve_markets_api_endpoint(timeout=MARKETS_API_WAKE_SECONDS)
    return MarketsClient(
        endpoint.url, headers=endpoint.headers, timeout=MARKETS_API_REQUEST_SECONDS
    )


def wait_for_metatables_api() -> None:
    """Resolve this process's MetaTables API, waiting for a scaled-to-zero API to wake.

    The client caches the endpoint for the process, so later calls reuse it.
    """
    from metatables.endpoint import api_endpoint_scope, resolve_api_endpoint

    with api_endpoint_scope(discovery_timeout=METATABLES_API_WAKE_SECONDS):
        resolve_api_endpoint()


def use_markets_api() -> None:
    """Serve every Markets row class of this process through the Markets API (idempotent)."""
    from msm.api.remote import active_remote_backend, use_remote_backend
    from msm.client import LazyRemoteBackend

    if active_remote_backend() is None:
        use_remote_backend(LazyRemoteBackend(markets_api_client))


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
    wait_for_metatables_api()
    use_markets_api()
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
    "MARKETS_API_REQUEST_SECONDS",
    "MARKETS_API_WAKE_SECONDS",
    "METATABLES_API_WAKE_SECONDS",
    "ROW_MODEL_NAME",
    "application_runtime_models",
    "markets_api_client",
    "markets_runtime",
    "project_models",
    "start_markets_engine",
    "use_markets_api",
    "wait_for_metatables_api",
]
