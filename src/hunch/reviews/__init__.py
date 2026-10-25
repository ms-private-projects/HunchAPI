"""Daily reviews: the audit of the daily loop over every active take."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from hunch.funding import HunchRebalanceProposalTable
from hunch.metatables import HunchMarketsMetaTableMixin, ProjectStorageNameMixin
from hunch.profiles import utc_now
from hunch.settings import PROJECT_NAMESPACE_SLUG
from hunch.takes import TakeTable
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args, new_markets_uid


class HunchDailyReviewTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per take per review date."""

    __project_storage_concept__ = "daily_review"
    __markets_base_identifier__ = "HunchDailyReview"
    __metatable_description__ = (
        "The daily review of an active take: weight drift against the target basket, the thesis "
        "check (what changed, whether the conditions the person named have triggered), the outcome "
        "(hold, flagged, proposed, executed) and the proposal it produced, if any."
    )
    __metatable_labels__ = ["hunch", "takes", "reviews"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_daily_review",
    }
    __table_args__ = markets_table_args(
        "HunchDailyReview",
        Index(None, "take_uid", "review_date", unique=True),
        Index(None, "review_date"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
    )
    take_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
    )
    review_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    drift_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "description": "{max_abs_drift, total_abs_drift, positions: [{figi, target, current}]}"
        },
    )
    thesis_check_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        info={"description": "hold, flagged (thesis conditions triggered), proposed or executed."},
    )
    proposal_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{HunchRebalanceProposalTable.__table__.fullname}.uid", ondelete="SET NULL"),
        nullable=True,
    )
    inference_request_uids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class HunchDailyReview(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchDailyReviewTable``."""

    __table__: ClassVar[type[HunchDailyReviewTable]] = HunchDailyReviewTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        TakeTable,
        HunchRebalanceProposalTable,
        HunchDailyReviewTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("take_uid", "review_date")

    take_uid: uuid.UUID
    review_date: dt.date
    drift_json: dict[str, Any] | None = None
    thesis_check_json: dict[str, Any] | None = None
    outcome: str
    proposal_uid: uuid.UUID | None = None
    inference_request_uids: list[str] | None = None
    summary_md: str = ""
    created_at: dt.datetime | None = None


def project_review_models() -> list[type[Any]]:
    return [HunchDailyReviewTable]


__all__ = ["HunchDailyReview", "HunchDailyReviewTable", "project_review_models"]
