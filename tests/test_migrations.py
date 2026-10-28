"""The `hunch` migration provider ships one head that creates exactly the project tables."""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

from hunch.migrations import PROJECT_TABLE_NAMES, all_project_metatable_models, migration
from hunch.migrations.schema_gate import (
    GATED_PROVIDERS,
    MIGRATION_PROVIDERS,
    code_head_revision,
    load_provider,
    script_directory,
)

VERSIONS = Path(__file__).resolve().parents[1] / "src/hunch/migrations/versions/hunch"


def _revision_module(name: str):
    path = next(VERSIONS.glob(f"{name}_*.py"))
    spec = importlib.util.spec_from_file_location(f"hunch_revision_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _offline_sql(run) -> str:
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": buffer},
    )
    with Operations.context(context):
        run()
    return buffer.getvalue()


def test_provider_identity_and_version_location() -> None:
    assert migration.package == "hunch"
    assert migration.migration_namespace == "hunch"
    assert tuple(migration.version_locations) == ("hunch.migrations:versions/hunch",)
    assert MIGRATION_PROVIDERS == ("hunch.migrations:migration",)
    # Hunch reaches the ms-markets schema only through the Markets API (ADR 0006).
    assert GATED_PROVIDERS == MIGRATION_PROVIDERS


def test_provider_loads_by_reference_with_a_single_head() -> None:
    loaded = load_provider("hunch.migrations:migration")
    assert code_head_revision(script_directory(loaded)) == "0004"


def test_revisions_create_every_project_table_with_its_model_columns() -> None:
    sql = "\n".join(
        _offline_sql(_revision_module(name).upgrade) for name in ("0001", "0002", "0003", "0004")
    )
    created = set(re.findall(r"CREATE TABLE (\w+) \(", sql))
    assert created == PROJECT_TABLE_NAMES
    for model in all_project_metatable_models():
        table = model.__table__
        block = re.search(rf"CREATE TABLE {table.name} \((.*?)\n\);", sql, re.S)
        assert block is not None, table.name
        declared = {line.strip().split(" ")[0] for line in block.group(1).splitlines()}
        assert {column.name for column in table.columns} <= declared, table.name
        for constraint in table.foreign_key_constraints:
            assert constraint.name in sql, (table.name, constraint.name)
        for index in table.indexes:
            assert index.name in sql, (table.name, index.name)


def test_downgrades_drop_every_project_table() -> None:
    sql = "\n".join(
        _offline_sql(_revision_module(name).downgrade) for name in ("0004", "0003", "0002", "0001")
    )
    assert set(re.findall(r"DROP TABLE (\w+);", sql)) == PROJECT_TABLE_NAMES
