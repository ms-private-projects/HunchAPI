"""Research one take: the thesis against the target universe, stored as a numbered research.

The API starts a run with `--take-uid <uid>` (and optionally `--research-mode`). The launcher
first checks that the database schema is not behind this image, attaches the markets runtime
once, researches, and prints a JSON summary. It decides no weight and builds no portfolio: that
is the Hunch Take Build Job, started separately from a stored research (ADR 0008). A failure
exits 1.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research one Hunch take.")
    parser.add_argument("--take-uid", required=True)
    parser.add_argument("--research-mode", choices=("inference", "heuristic"), default=None)
    args = parser.parse_args(argv)

    from hunch.migrations.schema_gate import skip_if_schema_behind

    if skip_if_schema_behind("Hunch Take Research"):
        return 0

    from hunch.research.runs import run_take_research
    from hunch.runtime import start_markets_engine

    start_markets_engine()
    try:
        result = run_take_research(args.take_uid, mode=args.research_mode, created_by="job")
    except Exception as exc:
        print(
            json.dumps({"take_uid": args.take_uid, "state": "failed", "error": type(exc).__name__})
        )
        print(f"Hunch Take Research failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "take_uid": args.take_uid,
                "state": "researched",
                "research_uid": str(result.research.uid),
                "number": result.research.number,
                "mode": result.output.mode,
                "candidates": len(result.output.candidates),
                "evidence": len(result.output.evidence),
                "inference_requests": len(result.output.inference_request_uids),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
