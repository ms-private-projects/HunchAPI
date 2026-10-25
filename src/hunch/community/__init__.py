"""Community tables: the nightly leaderboard and the in-app notification feed."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from hunch.metatables import HunchMarketsMetaTableMixin, ProjectStorageNameMixin
from hunch.profiles import HunchUserProfileTable, utc_now
from hunch.settings import PROJECT_NAMESPACE_SLUG
from hunch.takes import TakeTable
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args, new_markets_uid


class HunchLeaderboardSnapshotTable(
    ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase
):
    """One row per public take per snapshot date."""

    __project_storage_concept__ = "leaderboard_snapshot"
    __markets_base_identifier__ = "HunchLeaderboardSnapshot"
    __metatable_description__ = (
        "The nightly ranking of published takes by return since activation, with days active and "
        "whether the period is simulated (practice) or funded."
    )
    __metatable_labels__ = ["hunch", "community", "leaderboard"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_leaderboard_snapshot",
    }
    __table_args__ = markets_table_args(
        "HunchLeaderboardSnapshot",
        Index(None, "snapshot_date", "take_uid", unique=True),
        Index(None, "snapshot_date", "rank"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
    )
    snapshot_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    take_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    return_since_activation: Mapped[float] = mapped_column(Float, nullable=False)
    days_active: Mapped[int] = mapped_column(Integer, nullable=False)
    value_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_funded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class HunchNotificationTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per notification to one Hunch user."""

    __project_storage_concept__ = "notification"
    __markets_base_identifier__ = "HunchNotification"
    __metatable_description__ = (
        "The in-app feed: build results, daily review summaries, proposals awaiting approval, "
        "executions and funding events, per user, with read state and delivered channels."
    )
    __metatable_labels__ = ["hunch", "community", "notifications"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_notification",
    }
    __table_args__ = markets_table_args(
        "HunchNotification",
        Index(None, "user_uid", "created_at"),
        Index(None, "take_uid"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
    )
    user_uid: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{HunchUserProfileTable.__table__.fullname}.user_uid", ondelete="CASCADE"),
        nullable=False,
    )
    take_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeTable.__table__.fullname}.uid", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        info={
            "description": (
                "take_built, review_hold, review_proposed, proposal_awaiting_approval, "
                "proposal_executed, proposal_failed, funding_active, funding_closed, "
                "account_linked, take_forked."
            )
        },
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_channels_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class HunchLeaderboardSnapshot(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchLeaderboardSnapshotTable``."""

    __table__: ClassVar[type[HunchLeaderboardSnapshotTable]] = HunchLeaderboardSnapshotTable
    __required_tables__: ClassVar[list[type[Any]]] = [TakeTable, HunchLeaderboardSnapshotTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("snapshot_date", "take_uid")

    snapshot_date: dt.date
    take_uid: uuid.UUID
    rank: int
    return_since_activation: float
    days_active: int
    value_points: int = 0
    is_simulated: bool = True
    is_funded: bool = False
    created_at: dt.datetime | None = None


class HunchNotification(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchNotificationTable``."""

    __table__: ClassVar[type[HunchNotificationTable]] = HunchNotificationTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        HunchUserProfileTable,
        TakeTable,
        HunchNotificationTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("uid",)

    user_uid: str
    take_uid: uuid.UUID | None = None
    kind: str
    title: str
    body_md: str = ""
    payload_json: dict[str, Any] | None = None
    created_at: dt.datetime | None = None
    read_at: dt.datetime | None = None
    delivered_channels_json: list[str] | None = None


def project_community_models() -> list[type[Any]]:
    return [HunchLeaderboardSnapshotTable, HunchNotificationTable]


__all__ = [
    "HunchLeaderboardSnapshot",
    "HunchLeaderboardSnapshotTable",
    "HunchNotification",
    "HunchNotificationTable",
    "project_community_models",
]
