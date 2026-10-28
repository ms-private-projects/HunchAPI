"""Project-owned ms-markets MetaTable mixins for Hunch.

These set the physical-table *app segment* to this project's namespace so Hunch tables are named
``hunch__<table>`` instead of the library default ``ms_markets__<table>``. Logical identity
(``__metatable_identifier__``), registration, schema, namespace and constraint naming are inherited
from the ms-markets base mixins unchanged, exactly as the Alpaca and IBKR connectors do.

Use:
- ``HunchMarketsMetaTableMixin`` for regular (non-time-indexed) MetaTables.
- ``HunchMarketsTimeIndexMetaTableMixin`` for storage-first time-index storage classes.
- ``ProjectStorageNameMixin`` (placed *before* the Markets mixin in the base list) to give a short
  explicit physical ``__tablename__`` from ``__project_storage_concept__``.
"""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy.orm import declared_attr

from hunch.settings import MIGRATION_NAMESPACE, PROJECT_NAMESPACE_SLUG
from metatables import schema_table_name
from msm.base import MarketsMetaTableMixin, MarketsTimeIndexMetaTableMixin
from msm.settings import markets_auto_register_namespace

# Physical-table app segment for this project's MetaTables.
PROJECT_TABLE_APP = PROJECT_NAMESPACE_SLUG
# Catalog namespace of every Hunch MetaTable (ADR 0047 decision 4), the migration provider's own.
PROJECT_METATABLE_NAMESPACE = MIGRATION_NAMESPACE


class HunchMarketsMetaTableMixin(MarketsMetaTableMixin):
    """Regular markets MetaTable mixin using this project's table-name app segment."""

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = PROJECT_METATABLE_NAMESPACE
    __markets_storage_app__: ClassVar[str] = PROJECT_TABLE_APP


class HunchMarketsTimeIndexMetaTableMixin(MarketsTimeIndexMetaTableMixin):
    """Time-indexed (storage-first) markets MetaTable mixin using this project's app segment."""

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = PROJECT_METATABLE_NAMESPACE
    __markets_storage_app__: ClassVar[str] = PROJECT_TABLE_APP


class ProjectStorageNameMixin:
    """Override the physical ``__tablename__`` with a short explicit concept name.

    Placed *before* the Markets mixin in the base class list so it wins MRO. Leaves the logical
    ``__metatable_identifier__`` (catalog identity) untouched.
    """

    __project_storage_concept__: ClassVar[str]

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805 - SQLAlchemy declared_attr receives the class
        concept = cls.__project_storage_concept__
        cadence = getattr(cls, "__cadence__", None)
        if cadence:
            concept = f"{concept}_{cadence}"
        return schema_table_name(
            PROJECT_TABLE_APP,
            concept,
            suffix=markets_auto_register_namespace(),
        )


__all__ = [
    "PROJECT_TABLE_APP",
    "HunchMarketsMetaTableMixin",
    "HunchMarketsTimeIndexMetaTableMixin",
    "ProjectStorageNameMixin",
]
