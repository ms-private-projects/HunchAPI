"""Apply the MetaTable schema revisions this application reads before it rolls out.

The deployment workflow runs this Job from the candidate image on every push. It applies schema
revisions only, and only this application's provider: the ms-markets schema is migrated by the
ms-markets deployment's own Job. An exception fails the Job, which blocks the rollout while the
previous release keeps serving.
"""

from __future__ import annotations

import json


def main() -> int:
    from hunch.migrations.schema_gate import MIGRATION_PROVIDERS
    from metatables import upgrade_application

    for provider in MIGRATION_PROVIDERS:
        result = upgrade_application(provider)
        print(
            json.dumps(
                {
                    "provider": provider,
                    "revision": result.get("revision"),
                    "state": "migrated" if result.get("migrated") else "already current",
                    "data_source_uid": result.get("data_source_uid"),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
