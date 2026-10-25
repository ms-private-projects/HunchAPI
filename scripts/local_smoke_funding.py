"""Local smoke test of the funded-take loop against the MetaTables runtime and the simulated venue.

Run with the local MetaTables API up and migrated:

    HUNCH_CONNECTOR_MODE=simulated HUNCH_RESEARCH_MODE=heuristic \\
      PYTHONPATH=src .venv/bin/python scripts/local_smoke_funding.py [--take-uid UID]

It links a simulated paper account for the signed-in developer, funds a built take (creating and
building one when none is given), approves the initial trades, runs a review, withdraws, and prints
what every step recorded. It never touches a hosted environment or a real connector.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hunch local funding smoke test.")
    parser.add_argument("--take-uid", default=None)
    parser.add_argument("--notional", type=float, default=20_000.0)
    parser.add_argument("--user-uid", default=None, help="Default: the SDK sign-in's user.")
    args = parser.parse_args(argv)
    if os.environ.get("HUNCH_CONNECTOR_MODE", "simulated") != "simulated":
        print("This smoke test only runs with HUNCH_CONNECTOR_MODE=simulated.", file=sys.stderr)
        return 2
    os.environ.setdefault("HUNCH_CONNECTOR_MODE", "simulated")
    os.environ.setdefault("HUNCH_RESEARCH_MODE", "heuristic")
    if os.environ.get("APP_NAME"):
        print("Refusing to run inside a hosted runtime.", file=sys.stderr)
        return 2

    from metatables import configure_local_client

    configure_local_client()
    from hunch.funding import HunchFunding
    from hunch.funding.services import (
        FundingRequest,
        approve_proposal,
        fund_summary,
        fund_take,
        withdraw_take,
    )
    from hunch.operations.reviews import run_review
    from hunch.portfolios.build import activate_practice, build_take
    from hunch.profiles.accounts import link_holdings, start_link
    from hunch.runtime import start_markets_engine
    from hunch.takes import Take
    from hunch.takes.services import TakeCreate, create_take
    from mainsequence.client.utils import get_authorization_headers

    start_markets_engine()
    if args.user_uid:
        user_uid, username = args.user_uid, None
    else:
        base = os.environ["MAINSEQUENCE_ENDPOINT"].rstrip("/")
        me = requests.get(
            f"{base}/api/v1/users/me/", headers=get_authorization_headers(), timeout=30
        )
        me.raise_for_status()
        user_uid, username = str(me.json()["uid"]), me.json().get("username")

    def show(label: str, payload) -> None:
        print(f"== {label}: {json.dumps(payload, default=str)[:900]}")

    take_uid = args.take_uid
    if take_uid is None:
        take = create_take(
            user_uid,
            TakeCreate(
                title="Smoke: robots at home",
                thesis_text="Humanoid robots are coming to every home within the decade.",
            ),
            username=username,
        )
        build_take(take.uid, research_mode="heuristic", created_by="smoke")
        activate_practice(take.uid)
        take_uid = str(take.uid)
        show("take built", {"uid": take_uid})
    link = start_link(user_uid, "alpaca", account_name="Smoke simulated account")
    show("link", {"uid": link.uid, "account": (link.metadata_json or {}).get("account_identifier")})
    funding, proposal = fund_take(
        user_uid,
        take_uid,
        FundingRequest(profile_account_uid=link.uid, target_notional=args.notional),
    )
    show("proposal", {"status": proposal.status, "legs": len(proposal.legs_json)})
    approved = approve_proposal(user_uid, proposal.uid)
    show("approved", {"status": approved.status})
    funding = HunchFunding.get_by_uid(funding.uid)
    show(
        "funding",
        {
            "status": funding.status,
            **{k: v for k, v in fund_summary(funding).items() if k != "positions"},
        },
    )
    review = run_review(take_uid)
    show(
        "review",
        {"outcome": review.outcome, "verdict": (review.thesis_check_json or {}).get("verdict")},
    )
    withdrawn = withdraw_take(user_uid, take_uid)
    show("withdraw", {"status": withdrawn.status, "legs": len(withdrawn.legs_json)})
    snapshot = link_holdings(link)
    show("account", {"cash": round(snapshot.cash(), 2), "positions": len(snapshot.positions())})
    show("take", {"status": Take.get_by_uid(take_uid).status})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
