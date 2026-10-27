"""Instruments: the venue-neutral identity a take names its constituents by.

A `HunchInstrument` is keyed by FIGI, the identity ms-markets recommends, and points at the
canonical ms-markets `Asset` row (`unique_identifier` = FIGI) that the signal, the portfolio graph
and the price table use. Venue connectors register their own provider-native `Asset` rows (Alpaca
UUID, `IBKR::<conid>`); the mapping from an instrument to those rows comes with funding.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from pydantic import AliasChoices, Field
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from hunch.metatables import HunchMarketsMetaTableMixin, ProjectStorageNameMixin
from hunch.profiles import utc_now
from hunch.settings import PROJECT_NAMESPACE_SLUG
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args
from msm.models import AssetTable


class HunchInstrumentTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per instrument Hunch can put in a basket, keyed by FIGI."""

    __project_storage_concept__ = "instrument"
    __markets_base_identifier__ = "HunchInstrument"
    __metatable_description__ = (
        "One row per US-listed instrument Hunch can hold: FIGI identity, ticker, name, exchange, "
        "security type, sector and theme tags used by research, tradability and leverage flags, "
        "and the canonical ms-markets Asset the signal and prices are keyed on."
    )
    __metatable_labels__ = ["hunch", "instruments", "assets"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_instrument",
    }
    __table_args__ = markets_table_args(
        "HunchInstrument",
        Index(None, "asset_uid", unique=True),
        Index(None, "ticker"),
        Index(None, "sector"),
    )

    figi: Mapped[str] = mapped_column(
        String(12),
        primary_key=True,
        nullable=False,
        info={
            "label": "FIGI",
            "description": "OpenFIGI identifier; also the Asset unique_identifier.",
        },
    )
    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=False,
        info={
            "label": "Asset UID",
            "description": "Canonical ms-markets Asset of this instrument.",
        },
    )
    ticker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={"label": "Ticker", "description": "US listing ticker."},
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={"label": "Name", "description": "Issuer or fund name."},
    )
    exchange_code: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        info={"label": "Exchange", "description": "OpenFIGI exchange code (US for the composite)."},
    )
    security_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={"label": "Security type", "description": "OpenFIGI security type."},
    )
    sector: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        info={"label": "Sector", "description": "Sector label used by research and guardrails."},
    )
    themes_json: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        info={"label": "Themes", "description": "Theme tags the heuristic research matches on."},
    )
    is_etf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_leveraged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_inverse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_tradable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        info={
            "label": "Tradable",
            "description": "False excludes the instrument from new baskets.",
        },
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class HunchInstrument(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchInstrumentTable``."""

    __table__: ClassVar[type[HunchInstrumentTable]] = HunchInstrumentTable
    __required_tables__: ClassVar[list[type[Any]]] = [HunchInstrumentTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("figi",)

    uid: str = Field(validation_alias=AliasChoices("uid", "figi"))
    figi: str
    asset_uid: uuid.UUID
    ticker: str
    name: str
    exchange_code: str | None = None
    security_type: str | None = None
    sector: str | None = None
    themes_json: list[str] | None = None
    is_etf: bool = False
    is_leveraged: bool = False
    is_inverse: bool = False
    is_tradable: bool = True
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    metadata_json: dict[str, Any] | None = None

    @property
    def themes(self) -> list[str]:
        return list(self.themes_json or [])


def project_instrument_models() -> list[type[Any]]:
    return [HunchInstrumentTable]


__all__ = ["HunchInstrument", "HunchInstrumentTable", "project_instrument_models"]
