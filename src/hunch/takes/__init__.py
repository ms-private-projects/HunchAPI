"""Takes: a person's thesis, stated in natural language, and its product state.

The take is the unit of identity, sharing and ranking. Its basket, weights and performance live
in ms-markets through the take's ``HunchPortfolio`` (``hunch.portfolios``); the thesis text, the
constraints the person set, the execution mode, visibility and fork lineage live here.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from hunch.metatables import HunchMarketsMetaTableMixin, ProjectStorageNameMixin
from hunch.profiles import HunchUserProfileTable, utc_now
from hunch.settings import PROJECT_NAMESPACE_SLUG
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args, new_markets_uid
from msm_portfolios.models import SignalMetadataTable


class TakeTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per take."""

    __project_storage_concept__ = "take"
    __markets_base_identifier__ = "HunchTake"
    __metatable_description__ = (
        "One row per Hunch take: a person's investment thesis in natural language with its "
        "title, constraints (horizon, cash buffer, exclusions, risk), lifecycle status, "
        "execution mode (practice, approval, autopilot), visibility and fork lineage. The basket, "
        "weights and performance are ms-markets rows reached through the take's HunchPortfolio."
    )
    __metatable_labels__ = ["hunch", "takes", "theses"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_take",
    }
    __table_args__ = markets_table_args(
        "HunchTake",
        Index(None, "owner_user_uid"),
        Index(None, "status"),
        Index(None, "visibility"),
        Index(None, "origin_take_uid"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={"label": "UID", "description": "Public UUID of the take."},
    )
    owner_user_uid: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{HunchUserProfileTable.__table__.fullname}.user_uid", ondelete="CASCADE"),
        nullable=False,
        info={"label": "Owner", "description": "The Hunch user who wrote the take."},
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={"label": "Title", "description": "Short public title of the take."},
    )
    thesis_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        info={"label": "Thesis", "description": "The thesis in the person's own words."},
    )
    constraints_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Constraints",
            "description": (
                "Structured constraints: horizon, cash buffer, exclusions, risk level, whether "
                "leveraged or inverse products are allowed."
            ),
        },
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        info={
            "label": "Status",
            "description": "draft, built, active_practice, funding, active_funded or archived.",
        },
    )
    execution_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="practice",
        info={"label": "Execution mode", "description": "practice, approval or autopilot."},
    )
    visibility: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="private",
        info={"label": "Visibility", "description": "private or public."},
    )
    # Fork lineage. These are take UIDs without a database foreign key: the ms-markets runtime
    # orders MetaTables by their foreign-key graph and rejects a self-reference as a cycle. The
    # take services validate that both point at existing takes (ADR 0001, decision 7).
    forked_from_take_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={"label": "Forked from", "description": "The take this one was forked from."},
    )
    origin_take_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Origin",
            "description": "The first take in the fork lineage, credited on the leaderboard.",
        },
    )
    signal_uid: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey(f"{SignalMetadataTable.__table__.fullname}.signal_uid", ondelete="SET NULL"),
        nullable=True,
        info={
            "label": "Signal UID",
            "description": "ms-markets SignalMetadata of the take's weight signal, once built.",
        },
    )
    activated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Activated at",
            "description": "Start of the performance record (UTC).",
        },
    )
    published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={"label": "Published at", "description": "When the take became public (UTC)."},
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        info={"label": "Created at", "description": "When the take was created (UTC)."},
    )
    # Services set updated_at explicitly: a Python-side `onupdate` default does not travel
    # through the MetaTables compiled-SQL update path.
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        info={"label": "Updated at", "description": "When the take last changed (UTC)."},
    )


class Take(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``TakeTable``."""

    __table__: ClassVar[type[TakeTable]] = TakeTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        HunchUserProfileTable,
        SignalMetadataTable,
        TakeTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("uid",)

    owner_user_uid: str
    title: str
    thesis_text: str
    constraints_json: dict[str, Any] | None = None
    status: str = "draft"
    execution_mode: str = "practice"
    visibility: str = "private"
    forked_from_take_uid: uuid.UUID | None = None
    origin_take_uid: uuid.UUID | None = None
    signal_uid: str | None = None
    activated_at: dt.datetime | None = None
    published_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


def project_take_models() -> list[type[Any]]:
    """Project-owned MetaTables of this package."""
    return [TakeTable]


__all__ = ["Take", "TakeTable", "project_take_models"]
