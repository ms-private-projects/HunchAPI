"""HunchPortfolio: Hunch's portfolio type, an ms-markets ``Portfolio`` extended one-to-one.

ms-markets extends a model by relational composition, not inheritance: a detail table whose
primary key is the base row's uid (as ``OpenFigiAssetDetails`` and the connectors' detail tables
do). ``HunchPortfolioTable`` follows that convention: ``portfolio_uid`` is both its primary key
and a foreign key to ``PortfolioTable.uid``. Every Hunch attribute lives here; the base
``Portfolio`` keeps only what ``msm_portfolios`` needs, and every portfolio time series stays
keyed on the base ``Portfolio.unique_identifier``.

Hunch owns turning a take's basket into this portfolio (``hunch.portfolios.services``).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from pydantic import AliasChoices, Field
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from hunch.metatables import HunchMarketsMetaTableMixin, ProjectStorageNameMixin
from hunch.profiles import HunchUserProfileTable, utc_now
from hunch.settings import PROJECT_NAMESPACE_SLUG
from hunch.takes import TakeTable
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args
from msm.models import CalendarTable, PortfolioTable


class HunchPortfolioTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One-to-one extension of ``PortfolioTable`` for a take's portfolio."""

    __project_storage_concept__ = "portfolio"
    __markets_base_identifier__ = "HunchPortfolio"
    __metatable_description__ = (
        "One row per Hunch portfolio, keyed one-to-one by the ms-markets Portfolio it extends. "
        "Links the portfolio to its take and owner, records the basket revision it was built "
        "from, its activation and whether it is simulated (practice) or funded. Weights, "
        "rebalances and values stay in the ms-markets portfolio tables keyed on the base "
        "Portfolio."
    )
    __metatable_labels__ = ["hunch", "portfolios", "takes"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_portfolio",
    }
    __table_args__ = markets_table_args(
        "HunchPortfolio",
        Index(None, "take_uid", unique=True),
        Index(None, "owner_user_uid"),
    )

    portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{PortfolioTable.__table__.fullname}.uid", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        info={
            "label": "Portfolio UID",
            "description": "ms-markets Portfolio uid this row extends (primary key).",
        },
    )
    take_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={"label": "Take UID", "description": "The take this portfolio expresses."},
    )
    owner_user_uid: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{HunchUserProfileTable.__table__.fullname}.user_uid", ondelete="RESTRICT"),
        nullable=False,
        info={"label": "Owner", "description": "The Hunch user who owns the take."},
    )
    basket_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        info={
            "label": "Basket revision",
            "description": "Revision of the take's basket the current weights come from.",
        },
    )
    is_simulated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        info={
            "label": "Simulated",
            "description": "True while no money is invested (practice); false once funded.",
        },
    )
    activated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Activated at",
            "description": "First observation of the performance record (UTC).",
        },
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        info={"label": "Created at", "description": "When the portfolio was created (UTC)."},
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Construction details for display: engine settings, price source.",
        },
    )


class HunchPortfolio(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchPortfolioTable``."""

    __table__: ClassVar[type[HunchPortfolioTable]] = HunchPortfolioTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        HunchUserProfileTable,
        TakeTable,
        HunchPortfolioTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("portfolio_uid",)

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "portfolio_uid"))
    portfolio_uid: uuid.UUID
    take_uid: uuid.UUID
    owner_user_uid: str
    basket_revision: int = 1
    is_simulated: bool = True
    activated_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    metadata_json: dict[str, Any] | None = None


def project_portfolio_models() -> list[type[Any]]:
    """Project-owned MetaTables of this package."""
    return [HunchPortfolioTable]


__all__ = ["HunchPortfolio", "HunchPortfolioTable", "project_portfolio_models"]
