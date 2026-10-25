"""The instrument universe as a Command Center collection."""

from __future__ import annotations

from collections.abc import Iterable

from hunch.api.app.schemas import InstrumentResource, ResourceCollection
from hunch.api.app.services.common import validate_page_window
from hunch.instruments import HunchInstrument
from hunch.instruments.services import ensure_universe, list_instruments
from msm.api.http import (
    ResourceColumn,
    ResourceDiscovery,
    build_resource_collection,
    build_resource_discovery_spec,
    resolve_resource_discovery,
)

INSTRUMENTS_DISCOVERY = build_resource_discovery_spec(
    resource_id="instruments",
    label="Instruments",
    item_label="Instrument",
    identity_fields=("figi",),
    columns=(
        ResourceColumn(
            id="ticker",
            header="Ticker",
            value_path="ticker",
            data_type="text",
            importance="primary",
        ),
        ResourceColumn(id="name", header="Name", value_path="name", data_type="text"),
        ResourceColumn(id="sector", header="Sector", value_path="sector", data_type="text"),
        ResourceColumn(id="themes", header="Themes", value_path="themes", data_type="list"),
        ResourceColumn(
            id="figi", header="FIGI", value_path="figi", data_type="text", default_visible=False
        ),
        ResourceColumn(id="flags", header="Flags", value_path="flags", data_type="list"),
    ),
    search=True,
)
DISCOVERY_SPECS = {"instruments": INSTRUMENTS_DISCOVERY}


def instruments_discovery(query_keys: Iterable[str]) -> ResourceDiscovery:
    return resolve_resource_discovery("instruments", query_keys, specs=DISCOVERY_SPECS)


def instrument_resource(row: HunchInstrument) -> InstrumentResource:
    flags = [
        flag
        for flag, on in (
            ("etf", row.is_etf),
            ("leveraged", row.is_leveraged),
            ("inverse", row.is_inverse),
        )
        if on
    ]
    if not row.is_tradable:
        flags.append("not-tradable")
    return InstrumentResource(
        figi=row.figi,
        ticker=row.ticker,
        name=row.name,
        exchange_code=row.exchange_code,
        security_type=row.security_type,
        sector=row.sector,
        themes=row.themes,
        flags=flags,
        is_tradable=row.is_tradable,
    )


def list_instrument_resources(
    *, search: str | None = None, sector: str | None = None, limit: int = 25, offset: int = 0
) -> ResourceCollection:
    validate_page_window(limit, offset)
    rows = list_instruments()
    if sector:
        rows = [row for row in rows if (row.sector or "").lower() == sector.lower()]
    if search:
        needle = search.strip().lower()
        rows = [
            row
            for row in rows
            if needle in row.ticker.lower()
            or needle in row.name.lower()
            or any(needle in theme for theme in row.themes)
        ]
    page = rows[offset : offset + limit]
    collection = build_resource_collection(
        items=[instrument_resource(row).model_dump(mode="json") for row in page],
        limit=limit,
        offset=offset,
        total_items=len(rows),
    )
    return ResourceCollection.model_validate(collection.model_dump(by_alias=True))


def get_instrument_resource(identifier: str) -> InstrumentResource | None:
    wanted = identifier.strip().upper()
    for row in list_instruments():
        if row.figi.upper() == wanted or row.ticker.upper() == wanted:
            return instrument_resource(row)
    return None


def seed_instruments() -> int:
    return len(ensure_universe())


__all__ = [
    "DISCOVERY_SPECS",
    "INSTRUMENTS_DISCOVERY",
    "get_instrument_resource",
    "instrument_resource",
    "instruments_discovery",
    "list_instrument_resources",
    "seed_instruments",
]
