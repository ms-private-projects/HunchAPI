"""Build one take: research, guardrails, basket revision, signal and portfolio graph.

The API starts a run with `--take-uid <uid>` (and optionally `--research-mode`). The launcher
first checks that the database schema is not behind this image, attaches the markets runtime
once, builds, and prints a JSON summary. A failure exits 1.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one Hunch take.")
    parser.add_argument("--take-uid", required=True)
    parser.add_argument("--research-mode", choices=("inference", "heuristic"), default=None)
    args = parser.parse_args(argv)

    from hunch.migrations.schema_gate import skip_if_schema_behind

    if skip_if_schema_behind("Hunch Take Build"):
        return 0

    from hunch.portfolios.build import build_take
    from hunch.runtime import start_markets_engine

    start_markets_engine()
    try:
        result = build_take(args.take_uid, research_mode=args.research_mode, created_by="job")
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
