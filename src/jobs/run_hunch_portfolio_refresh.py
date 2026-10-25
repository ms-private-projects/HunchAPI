"""Refresh take portfolios: bring prices up to date and extend their values.

`--take-uid <uid>` refreshes one take; `--scheduled` refreshes every built take (the daily run the
workflow schedules after the market close). A failure on one take is reported and the run goes on;
the exit code is 1 when any take failed.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Hunch take portfolios.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--take-uid")
    group.add_argument("--scheduled", action="store_true")
    args = parser.parse_args(argv)

    from hunch.migrations.schema_gate import skip_if_schema_behind

    if skip_if_schema_behind("Hunch Portfolio Refresh"):
        return 0

    from hunch.portfolios.build import refresh_take_portfolio
    from hunch.runtime import start_markets_engine
    from hunch.takes import Take

    start_markets_engine()
    if args.take_uid:
        targets = [args.take_uid]
    else:
        targets = [
            str(row.uid)
            for row in Take.filter(limit=5000)
            if row.status in ("built", "active_practice", "funding", "active_funded")
        ]
    failures = 0
    for take_uid in targets:
        try:
            refresh_take_portfolio(take_uid)
            print(json.dumps({"take_uid": take_uid, "state": "refreshed"}), flush=True)
        except Exception as exc:
            failures += 1
            print(
                json.dumps({"take_uid": take_uid, "state": "failed", "error": type(exc).__name__})
            )
            print(f"Hunch Portfolio Refresh failed for {take_uid}: {exc}", file=sys.stderr)
    print(json.dumps({"refreshed": len(targets) - failures, "failed": failures}, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
