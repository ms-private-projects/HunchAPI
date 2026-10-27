"""Re-home Hunch tables registered before Hunch declared its own catalog namespace (ADR 0006).

Until revision 0003 the Hunch mixins inherited ``mainsequence.markets``, so the product tables
were catalogued there with bare identifiers (``HunchUserProfile``). Under the Markets API boundary
every row class whose table is catalogued in the Markets namespace is served by the Markets API,
which has no Hunch resources, so each table must be catalogued in ``hunch`` with its namespaced
identifier (``hunch.HunchUserProfile``) before any Hunch process starts on this code.

The move is a catalog update of each table in place (``PATCH /meta-tables/<uid>/``): the table
keeps its uid, physical name, rows, grants and Alembic binding. It is idempotent and runs in the
migration Job before the provider upgrade. It touches only tables bound to this provider.
"""

from __future__ import annotations

from typing import Any

PROVIDER_KEY_SUFFIX = ":hunch"


def _bound_to_this_provider(row: Any) -> bool:
    key = str(getattr(row, "migration_provider_key", "") or "")
    namespace = str(getattr(row, "migration_namespace", "") or "")
    return key.endswith(PROVIDER_KEY_SUFFIX) or namespace == "hunch"


def move_project_tables_to_namespace(*, dry_run: bool = False) -> list[dict[str, str]]:
    """Catalogue every project table in its declared namespace; return what moved."""
    from hunch.migrations import all_project_metatable_models
    from metatables import MetaTable

    moved: list[dict[str, str]] = []
    for model in all_project_metatable_models():
        table = model.__table__
        namespace = str(table.info["namespace"])
        identifier = str(table.info["identifier"])
        for row in MetaTable.filter(physical_table_name=table.name):
            if not _bound_to_this_provider(row):
                continue
            if row.namespace == namespace and row.identifier == identifier:
                continue
            moved.append(
                {
                    "physical_table_name": table.name,
                    "from": f"{row.namespace}/{row.identifier}",
                    "to": f"{namespace}/{identifier}",
                }
            )
            if not dry_run:
                MetaTable.patch_by_uid(str(row.uid), identifier=identifier, namespace=namespace)
    return moved


def main(argv: list[str] | None = None) -> int:
    """Local use: ``python -m hunch.migrations.namespace_move --local [--dry-run]``."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Catalogue the Hunch tables in `hunch`.")
    parser.add_argument("--local", action="store_true", help="Use the local MetaTables runtime.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.local:
        from metatables import configure_local_client

        configure_local_client()
    print(json.dumps(move_project_tables_to_namespace(dry_run=args.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "move_project_tables_to_namespace"]
