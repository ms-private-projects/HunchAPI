"""Loopback Markets API for local development (ADR 0047 boundary, Hunch ADR 0006).

Run with the interpreter of an ms-markets checkout, from that checkout:

    cd ../mainsequencemarkets-* && .venv/bin/python ../hunchapi-*/scripts/local_markets_api.py

It serves the checkout's `api.main:app` on 127.0.0.1 (default port 8603) against the local
MetaTables runtime, and Hunch processes reach it with `MARKETS_API_URL`. The deployed Markets API
verifies every Bearer token with the Main Sequence backend; this launcher reuses each verified
identity until its token expires, so a take build does not wait on that lookup for every registry
call, and it installs Hunch's SQLite compat shims (ADR 0002), which the Markets API now hits.
It accepts loopback connections only and must never run behind a public proxy.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import threading
import time
from pathlib import Path

IDENTITY_TTL_SECONDS = 300
VERIFY_ATTEMPTS = 8
VERIFY_BACKOFF_SECONDS = 1.0


def _cache_local_identity() -> None:
    """Keep each verified identity until its token expires, and retry a failed verification.

    Every distinct token is still verified with the Main Sequence backend by the SDK; a result is
    reused only for the same token and never beyond `IDENTITY_TTL_SECONDS` (the SDK token's
    lifetime). A failed verification is retried, because the local backend is often slow.
    """
    from mainsequence.server import fastapi as identity

    original = identity._local_user
    if getattr(original, "_hunch_local_cache", False):
        return
    lock = threading.Lock()
    cache: dict[tuple[str, str | None], tuple[float, object]] = {}

    def cached(scope):
        authorization = identity._header(scope, b"authorization") or ""
        key = (
            hashlib.sha256(authorization.encode()).hexdigest(),
            identity._header(scope, b"x-user-uid"),
        )
        now = time.monotonic()
        with lock:
            hit = cache.get(key)
            if hit is not None and now - hit[0] < IDENTITY_TTL_SECONDS:
                return hit[1]
        for attempt in range(VERIFY_ATTEMPTS):
            try:
                user = original(scope)
                break
            except Exception as exc:
                # Only an unavailable backend (503) is worth another attempt.
                if getattr(exc, "status", None) != 503 or attempt == VERIFY_ATTEMPTS - 1:
                    raise
                time.sleep(VERIFY_BACKOFF_SECONDS)
        with lock:
            cache[key] = (now, user)
        return user

    cached._hunch_local_cache = True  # type: ignore[attr-defined]
    identity._local_user = cached


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loopback Markets API for Hunch development.")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("HUNCH_LOCAL_MARKETS_PORT", "8603"))
    )
    args = parser.parse_args(argv)
    if any(os.environ.get(name) for name in ("APP_NAME", "FASTAPI_PUBLIC_BASE_URL")):
        raise SystemExit(
            "The loopback Markets launcher runs only outside a Main Sequence deployment."
        )
    sys.path.insert(0, os.getcwd())
    # Hunch's compat shims cover the ms-markets UUID binds on SQLite (ADR 0002), which the
    # Markets API now runs on behalf of Hunch.
    sys.path.insert(1, str(Path(__file__).resolve().parents[1] / "src"))
    from hunch.compat import install_compat_patches
    from metatables import configure_local_client

    install_compat_patches()
    configure_local_client()
    _cache_local_identity()
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
