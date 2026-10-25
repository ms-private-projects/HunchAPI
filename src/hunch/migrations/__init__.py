"""The ``hunch`` MetaTables migration provider.

Reference: ``hunch.migrations:migration``. It owns only the project tables in the ``hunch``
namespace. The ms-markets tables they reference (accounts, calendars, indices, signals,
portfolios) are metadata-only dependencies here: SQLAlchemy needs the full foreign-key closure to
sort the project tables, the include-name hook keeps them out of this provider's DDL, and the
ms-markets deployment's own migration Job owns their schema.
"""

from __future__ import annotations

from hunch.portfolios import project_portfolio_models
from hunch.profiles import project_profile_models
from hunch.settings import MIGRATION_NAMESPACE, PROJECT_NAMESPACE_SLUG
from hunch.takes import project_take_models
from metatables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
    metadata_for_models,
)
from msm.models import (
    AccountGroupTable,
    AccountTable,
    AssetTable,
    CalendarTable,
    IndexTable,
    IndexTypeTable,
    PortfolioTable,
)
from msm_portfolios.models import SignalMetadataTable


def all_project_metatable_models() -> list[type]:
    """Every project-owned MetaTable managed by this migration provider, in dependency order."""
    from hunch.instruments import project_instrument_models
    from hunch.takes.revisions import project_revision_models

    return [
        *project_profile_models(),
        *project_instrument_models(),
        *project_take_models(),
        *project_revision_models(),
        *project_portfolio_models(),
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


METADATA = metadata_for_models(
    [
        AssetTable,
        AccountGroupTable,
        AccountTable,
        CalendarTable,
        IndexTypeTable,
        IndexTable,
        SignalMetadataTable,
        PortfolioTable,
        *all_project_metatable_models(),
    ]
)

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
