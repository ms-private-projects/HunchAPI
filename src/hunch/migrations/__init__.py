"""The ``hunch`` MetaTables migration provider.

Reference: ``hunch.migrations:migration``. It owns the project tables and Hunch's time-series
instances, all in the ``hunch`` namespace (ADR 0006). The ms-markets tables they reference
(assets, accounts, calendars, portfolios, signals, funds, order batches) appear in this provider's
metadata only as key-only reference tables (``msm.storage_instances.markets_reference_table``):
SQLAlchemy needs the foreign-key targets to sort and compare, the include-name hook keeps them out
of this provider's DDL, and the Markets deployment's own migration Job owns their schema.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from hunch.portfolios import project_portfolio_models
from hunch.profiles import project_profile_models
from hunch.series import project_series_models
from hunch.settings import MIGRATION_NAMESPACE, PROJECT_NAMESPACE_SLUG
from hunch.takes import project_take_models
from metatables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
    metadata_for_models,
)
from msm.storage_instances import markets_reference_table


def all_project_metatable_models() -> list[type]:
    """Every project-owned MetaTable managed by this migration provider, in dependency order."""
    from hunch.community import project_community_models
    from hunch.funding import project_funding_models
    from hunch.instruments import project_instrument_models
    from hunch.reviews import project_review_models
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
        *project_series_models(),
    ]


PROJECT_TABLE_NAMES = frozenset(model.__table__.name for model in all_project_metatable_models())


def _include_project_tables(
    name: str | None,
    type_: str,
    parent_names: dict[str, object],
) -> bool:
    """Limit Alembic operations to this provider's project-owned tables."""
    del parent_names
    return type_ != "table" or name in PROJECT_TABLE_NAMES


def _with_markets_references(models: list[type]) -> MetaData:
    """The project tables plus a key-only copy of every Markets table they reference."""
    metadata = metadata_for_models(models)
    targets: dict[str, tuple[Table, set[str]]] = {}
    for model in models:
        for foreign_key in model.__table__.foreign_keys:
            column = foreign_key.column
            if column.table.name in PROJECT_TABLE_NAMES:
                continue
            core, columns = targets.setdefault(column.table.key, (column.table, set()))
            columns.add(column.name)
    for core, columns in targets.values():
        markets_reference_table(core, metadata, sorted(columns))
    return metadata


METADATA = _with_markets_references(all_project_metatable_models())

ProjectAlembicVersion = build_alembic_version_metatable(
    class_name="ProjectAlembicVersion",
    namespace=MIGRATION_NAMESPACE,
    identifier=f"{PROJECT_NAMESPACE_SLUG}.alembic_version",
    schema=None,
    table_name=f"{PROJECT_NAMESPACE_SLUG}__alembic_version",
)

SHARED_PROVIDER_KWARGS = {
    # Catalog binding key (`package:namespace`), frozen once the first hosted migration runs.
    "package": PROJECT_NAMESPACE_SLUG,
    "migration_namespace": MIGRATION_NAMESPACE,
    "script_location": "hunch.migrations:",
    "version_location_prefix": "hunch.migrations:versions",
    "alembic_registry": ProjectAlembicVersion,
}

migration = build_metatable_migration_provider(
    **SHARED_PROVIDER_KWARGS,
    target_metadata=METADATA,
    metatable_models=all_project_metatable_models(),
    include_name_hook=_include_project_tables,
)


__all__ = [
    "PROJECT_TABLE_NAMES",
    "ProjectAlembicVersion",
    "SHARED_PROVIDER_KWARGS",
    "all_project_metatable_models",
    "migration",
]
