"""Email digest: one message per person who opted in, from their undelivered notifications.

`--user-uid <uid>` sends one person's digest; `--scheduled` sends every opted-in person's (the
workflow runs it after the daily reviews). Notifications are marked delivered by email so a rerun
never repeats them; an empty digest is not sent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send Hunch email digests.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-uid")
    group.add_argument("--scheduled", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Compose only; send nothing.")
    args = parser.parse_args(argv)

    from hunch.migrations.schema_gate import skip_if_schema_behind

    if skip_if_schema_behind("Hunch Email Digest"):
        return 0

    from hunch.channels.delivery import send_digest_for
    from hunch.profiles import HunchUserProfile
    from hunch.runtime import start_markets_engine

    start_markets_engine()
    if args.user_uid:
        profiles = [row for row in [HunchUserProfile.get_by_uid(args.user_uid)] if row is not None]
    else:
        profiles = [
            row
            for row in HunchUserProfile.filter(limit=5000)
            if (row.metadata_json or {}).get("email_digest")
        ]
    site_url = os.environ.get("HUNCH_SITE_URL") or None
    sent = skipped = failed = 0
    for profile in profiles:
        try:
            outcome = send_digest_for(profile, site_url=site_url, dry_run=args.dry_run)
            print(json.dumps({"user_uid": profile.user_uid, **outcome}, default=str), flush=True)
            sent += outcome["state"] == "sent"
            skipped += outcome["state"] != "sent"
        except Exception as exc:
            failed += 1
            print(
                json.dumps(
                    {"user_uid": profile.user_uid, "state": "failed", "error": type(exc).__name__}
                )
            )
            print(f"Hunch Email Digest failed for {profile.user_uid}: {exc}", file=sys.stderr)
    print(json.dumps({"sent": sent, "skipped": skipped, "failed": failed}, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
