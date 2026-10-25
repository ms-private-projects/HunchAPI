"""Daily review of active takes: drift, thesis check, proposal or autopilot, notification.

`--take-uid <uid>` reviews one take; `--scheduled` reviews every active take (the workflow runs it
on US session days before the open). A failure on one take is reported and the run goes on; the
exit code is 1 when any take failed.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review Hunch takes.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--take-uid")
    group.add_argument("--scheduled", action="store_true")
    parser.add_argument("--research-mode", choices=("inference", "heuristic"), default=None)
    args = parser.parse_args(argv)

    from hunch.migrations.schema_gate import skip_if_schema_behind

    if skip_if_schema_behind("Hunch Daily Review"):
        return 0

    from hunch.operations.reviews import run_review
    from hunch.reviews.services import ACTIVE_STATUSES
    from hunch.runtime import start_markets_engine
    from hunch.takes import Take

    start_markets_engine()
    if args.take_uid:
        targets = [args.take_uid]
    else:
        targets = [str(row.uid) for row in Take.filter(limit=5000) if row.status in ACTIVE_STATUSES]
    failures = 0
    for take_uid in targets:
        try:
            review = run_review(take_uid, mode=args.research_mode)
            print(json.dumps({"take_uid": take_uid, "outcome": review.outcome}), flush=True)
        except Exception as exc:
            failures += 1
            print(
                json.dumps({"take_uid": take_uid, "state": "failed", "error": type(exc).__name__})
            )
            print(f"Hunch Daily Review failed for {take_uid}: {exc}", file=sys.stderr)
    print(json.dumps({"reviewed": len(targets) - failures, "failed": failures}, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
