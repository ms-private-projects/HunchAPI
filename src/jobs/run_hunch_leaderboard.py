"""Write the nightly leaderboard snapshot of published takes."""

from __future__ import annotations

import argparse
import datetime as dt
import json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot the Hunch leaderboard.")
    parser.add_argument("--date", default=None, help="Snapshot date (YYYY-MM-DD); default today.")
    args = parser.parse_args(argv)

    from hunch.migrations.schema_gate import skip_if_schema_behind

    if skip_if_schema_behind("Hunch Leaderboard"):
        return 0

    from hunch.community.leaderboard import snapshot_leaderboard
    from hunch.runtime import start_markets_engine

    start_markets_engine()
    date = dt.date.fromisoformat(args.date) if args.date else None
    rows = snapshot_leaderboard(date)
    print(
        json.dumps(
            {
                "snapshot_date": str(rows[0].snapshot_date) if rows else str(date),
                "entries": len(rows),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
