"""The instrument universe: seeding from the fixture and lookups.

Seeding writes, through ms-markets, the asset types, the canonical `Asset` row per FIGI, its
OpenFIGI details and first snapshot, and the `HUNCH_UNIVERSE` category; then the Hunch instrument
rows. It is idempotent: re-running only adds what is missing.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import msm.constants as C
from hunch.instruments import HunchInstrument
from hunch.profiles import utc_now
from hunch.settings import CASH_ASSET_IDENTIFIER, UNIVERSE_CATEGORY_IDENTIFIER
from msm.api.assets import Asset, AssetCategory, AssetType, OpenFigiDetails

FIXTURE_PATH = Path(__file__).with_name("universe.json")
# The instrument rows change only when `seed_universe` adds fixture instruments, so a read path
# (the take weights, every Basket tab load) serves them from one read per process for this long
# instead of one remote read per request.
UNIVERSE_CACHE_SECONDS = 300.0
_universe_cache: tuple[float, list[HunchInstrument]] | None = None


@lru_cache(maxsize=1)
def universe_fixture() -> list[dict[str, Any]]:
    """The packaged universe: tickers with FIGIs resolved through OpenFIGI."""
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    rows = payload["instruments"]
    figis = [row["figi"] for row in rows]
    if len(set(figis)) != len(figis):
        raise ValueError("The universe fixture repeats a FIGI.")
    return rows


def ensure_asset(unique_identifier: str, asset_type: str) -> Asset:
    """Get or create an Asset with a plain insert.

    An upsert on the asset key makes the governed SQL layer check every physical table that
    references it, including ones no runtime registers; a lookup plus insert does not.
    """
    existing = Asset.get_by_unique_identifier(unique_identifier)
    if existing is not None:
        return existing
    return Asset.create(unique_identifier=unique_identifier, asset_type=asset_type)


def ensure_cash_asset() -> Asset:
    AssetType.upsert(**C.ASSET_TYPE_CURRENCY_DEFINITION.as_payload())
    return ensure_asset(CASH_ASSET_IDENTIFIER, "currency")


def seed_universe(*, snapshot_time: dt.datetime | None = None) -> list[HunchInstrument]:
    """Register every fixture instrument that is missing and return the whole universe.

    Assets, their OpenFIGI details, snapshots and the universe category are Markets registries,
    written through the Markets API (ADR 0006); the instrument rows are Hunch's.
    """
    from msm.api.assets import AssetSnapshots

    AssetType.upsert(**C.ASSET_TYPE_EQUITY_DEFINITION.as_payload())
    ensure_cash_asset()
    existing = {row.figi: row for row in list_instruments()}
    snapshot_rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    now = snapshot_time or utc_now()
    for index, item in enumerate(universe_fixture()):
        if item["figi"] in existing:
            continue
        asset = ensure_asset(item["figi"], "equity")
        OpenFigiDetails.upsert(
            asset_uid=asset.uid,
            figi=item["figi"],
            composite=item.get("composite_figi"),
            share_class=item.get("share_class_figi"),
            ticker=item["ticker"],
            name=item.get("openfigi_name") or item["name"],
            exchange_code=item.get("exchange_code"),
            security_type=item.get("security_type"),
            security_type_2=item.get("security_type_2"),
            security_market_sector=item.get("market_sector"),
        )
        snapshot_rows.append(
            {
                # Each snapshot row needs its own time_index.
                "time_index": now + dt.timedelta(milliseconds=index),
                "asset_identifier": item["figi"],
                "name": item["name"],
                "ticker": item["ticker"],
                "exchange_code": item.get("exchange_code") or "US",
                "asset_ticker_group_id": item["ticker"],
            }
        )
        pending.append(
            {
                "figi": item["figi"],
                "asset_uid": asset.uid,
                "ticker": item["ticker"],
                "name": item["name"],
                "exchange_code": item.get("exchange_code"),
                "security_type": item.get("security_type"),
                "sector": item.get("sector"),
                "themes_json": list(item.get("themes") or []),
                "is_etf": bool(item.get("is_etf")),
                "is_leveraged": bool(item.get("is_leveraged")),
                "is_inverse": bool(item.get("is_inverse")),
                "is_tradable": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    if snapshot_rows:
        AssetSnapshots.publish(snapshot_rows)
    category = AssetCategory.upsert(
        unique_identifier=UNIVERSE_CATEGORY_IDENTIFIER,
        display_name="Hunch universe",
        description="Every instrument Hunch can hold; the price coverage set.",
    )
    AssetCategory.replace_memberships(
        category_uid=category.uid,
        asset_uids=[
            *(row.asset_uid for row in existing.values()),
            *(row["asset_uid"] for row in pending),
        ],
    )
    # Hunch's rows go last: `ensure_universe` takes them as the sign that the universe is seeded,
    # so a failure above leaves the instruments missing and the next build seeds again.
    for row in pending:
        HunchInstrument.upsert(**row)
    forget_cached_instruments()
    return list_instruments()


def list_instruments() -> list[HunchInstrument]:
    return sorted(HunchInstrument.filter(limit=5000), key=lambda row: row.ticker)


def ensure_universe() -> list[HunchInstrument]:
    """The universe, seeded on first use."""
    instruments = list_instruments()
    if len(instruments) >= len(universe_fixture()):
        return instruments
    return seed_universe()


def cached_instruments(*, now: float | None = None) -> list[HunchInstrument]:
    """The instrument rows, read at most once per ``UNIVERSE_CACHE_SECONDS`` in this process.

    Read paths use this; anything that writes instruments calls `forget_cached_instruments`.
    """
    global _universe_cache
    moment = time.monotonic() if now is None else now
    if _universe_cache is not None and moment - _universe_cache[0] < UNIVERSE_CACHE_SECONDS:
        return list(_universe_cache[1])
    rows = list_instruments()
    _universe_cache = (moment, rows)
    return list(rows)


def forget_cached_instruments() -> None:
    global _universe_cache
    _universe_cache = None


def instruments_by_ticker(instruments: Iterable[HunchInstrument]) -> dict[str, HunchInstrument]:
    return {row.ticker.upper(): row for row in instruments}


def instruments_by_figi(instruments: Iterable[HunchInstrument]) -> dict[str, HunchInstrument]:
    return {row.figi: row for row in instruments}


def instruments_for_figis(figis: Sequence[str]) -> dict[str, HunchInstrument]:
    wanted = set(figis)
    return {row.figi: row for row in list_instruments() if row.figi in wanted}


__all__ = [
    "FIXTURE_PATH",
    "ensure_asset",
    "ensure_cash_asset",
    "cached_instruments",
    "ensure_universe",
    "forget_cached_instruments",
    "instruments_by_figi",
    "instruments_by_ticker",
    "instruments_for_figis",
    "list_instruments",
    "seed_universe",
    "universe_fixture",
]
