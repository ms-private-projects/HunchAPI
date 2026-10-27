"""Prepare the laptop's local MetaTables runtime for Hunch development.

Local only. It never migrates: run the ms-markets and Hunch providers first
(`metatables --local migrations upgrade --provider ... head`). It then registers, in the catalog,
the physical tables ms-markets' migrations create but never register. SQLite's foreign-key
enforcement reads a child table when a parent key is inserted, and the local API's authorizer
grants only registered tables, so an unregistered child of `ms_markets__asset` blocks every asset
insert with "access to <table> is prohibited". Hosted PostgreSQL runtimes have no such step.

    .venv/bin/python scripts/local_prepare_runtime.py
"""

from __future__ import annotations

import sys


def main() -> int:
    from metatables import (
        MetaTable,
        configure_local_client,
        get_runtime_status,
        register_external_sqlalchemy_model,
    )

    configure_local_client()
    state = get_runtime_status()
    if state.get("local_mode") is not True or state.get("dialect") != "sqlite":
        print("This script prepares the local SQLite runtime only.", file=sys.stderr)
        return 2
    source = (state.get("data_source") or {}).get("uid")
    if not source:
        print("The local runtime has no data source; initialize it first.", file=sys.stderr)
        return 2

    from msm_portfolios.time_index.prices.storage import InterpolatedPricesStorage

    orphans = [
        (
            InterpolatedPricesStorage.__table__,
            "ms_markets.orphan.interpolated_prices_base",
            "Base interpolated-prices table created by ms-markets migrations; registered locally "
            "so SQLite foreign-key checks on asset inserts are permitted.",
        ),
    ]
    for table, identifier, description in orphans:
        physical = table.name
        existing = [
            registration
            for registration in MetaTable.filter(physical_table_name__in=[physical])
            if getattr(registration, "physical_table_name", None) == physical
        ]
        if existing:
            print(f"{physical}: already registered as {existing[0].identifier}")
            continue
        registration = register_external_sqlalchemy_model(
            table,
            data_source_uid=str(source),
            identifier=identifier,
            namespace="hunch-local",
            description=description,
        )
        print(f"{physical}: registered as {registration.identifier} ({registration.uid})")
    print(f"local runtime ready: {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
