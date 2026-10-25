"""Execution sync: pull order states from the venues, book fills, expire stale proposals.

`--proposal-uid <uid>` syncs one proposal; `--scheduled` syncs every submitted or partially filled
proposal and expires proposals past their deadline (the workflow runs it during US sessions).
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Hunch proposal execution.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--proposal-uid")
    group.add_argument("--scheduled", action="store_true")
    args = parser.parse_args(argv)

    from hunch.migrations.schema_gate import skip_if_schema_behind

    if skip_if_schema_behind("Hunch Execution Sync"):
        return 0

    from hunch.funding import HunchRebalanceProposal
    from hunch.funding.services import sync_open_proposals, sync_proposal
    from hunch.runtime import start_markets_engine

    start_markets_engine()
    try:
        if args.proposal_uid:
            proposal = HunchRebalanceProposal.get_by_uid(args.proposal_uid)
            if proposal is None:
                print(f"Proposal {args.proposal_uid} does not exist.", file=sys.stderr)
                return 1
            synced = [sync_proposal(proposal)]
        else:
            synced = sync_open_proposals()
    except Exception as exc:
        print(f"Hunch Execution Sync failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"synced": len(synced), "statuses": sorted({row.status for row in synced})}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
