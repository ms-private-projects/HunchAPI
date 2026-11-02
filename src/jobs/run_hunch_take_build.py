"""Build one take: construction from a stored research, basket revision, signal and portfolio.

The API starts a run with `--take-uid <uid>` (and optionally `--research-uid <uid>`; the take's
latest research otherwise). The launcher first checks that the database schema is not behind this
image, starts waking the Markets API, attaches the markets runtime once, builds, and prints a JSON
summary. It calls no model: research is the Hunch Take Research Job, run first (ADR 0008). A
failure exits 1.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one Hunch take.")
    parser.add_argument("--take-uid", required=True)
    parser.add_argument("--research-uid", default=None)
    args = parser.parse_args(argv)

    from hunch.migrations.schema_gate import skip_if_schema_behind

    if skip_if_schema_behind("Hunch Take Build"):
        return 0

    from hunch.portfolios.build import build_take
    from hunch.runtime import start_markets_engine, wake_markets_api

    # The Markets API scales to zero and the build first needs it after attaching the runtime and
    # constructing the basket, so it wakes meanwhile.
    wake_markets_api()
    start_markets_engine()
    try:
        result = build_take(args.take_uid, research_uid=args.research_uid, created_by="job")
    except Exception as exc:
        print(
            json.dumps({"take_uid": args.take_uid, "state": "failed", "error": type(exc).__name__})
        )
        print(f"Hunch Take Build failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "take_uid": args.take_uid,
                "state": "built",
                "research_uid": str(result.research.uid),
                "research_number": result.research.number,
                "revision": result.revision.revision,
                "signal_uid": result.signal_uid,
                "portfolio_identifier": result.portfolio_identifier,
                "positions": len(result.proposal.weights),
                "value_points": len(result.value_points),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
