"""Take revisions: every basket Hunch constructed for a take, and the research it came from."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from hunch.metatables import HunchMarketsMetaTableMixin, ProjectStorageNameMixin
from hunch.profiles import utc_now
from hunch.settings import PROJECT_NAMESPACE_SLUG
from hunch.takes import TakeTable
from hunch.takes.research import TakeResearchTable
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args, new_markets_uid


class TakeRevisionTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per basket revision of a take."""

    __project_storage_concept__ = "take_revision"
    __markets_base_identifier__ = "HunchTakeRevision"
    __metatable_description__ = (
        "One row per revision of a take's basket: the weights Hunch constructed, the stored "
        "research they came from (and a copy of its candidates, roles, evidence and risks), the "
        "rationale shown to people, the recorded inference requests behind it, and the signal "
        "observation time it published."
    )
    __metatable_labels__ = ["hunch", "takes", "revisions", "research"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_take_revision",
    }
    __table_args__ = markets_table_args(
        "HunchTakeRevision",
        Index(None, "take_uid", "revision", unique=True),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
    )
    take_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    research_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeResearchTable.__table__.fullname}.uid", ondelete="SET NULL"),
        nullable=True,
        info={"description": "The take research this basket was constructed from (ADR 0008)."},
    )
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={"description": "initial, rebalance, user_edit or thesis_check."},
    )
    rationale_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    weights_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        info={"description": "[{figi, ticker, weight, role, reason}] summing to 1 - cash buffer."},
    )
    research_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    inference_request_uids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="job",
        info={"description": "job, user or agent (the research row carries the mode)."},
    )
    signal_time_index: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TakeRevision(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``TakeRevisionTable``."""

    __table__: ClassVar[type[TakeRevisionTable]] = TakeRevisionTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        TakeTable,
        TakeResearchTable,
        TakeRevisionTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("take_uid", "revision")

    take_uid: uuid.UUID
    revision: int
    research_uid: uuid.UUID | None = None
    kind: str
    rationale_md: str = ""
    weights_json: list[dict[str, Any]]
    research_json: dict[str, Any] | None = None
    inference_request_uids: list[str] | None = None
    created_by: str = "job"
    signal_time_index: dt.datetime | None = None
    created_at: dt.datetime | None = None


def project_revision_models() -> list[type[Any]]:
    return [TakeRevisionTable]


__all__ = ["TakeRevision", "TakeRevisionTable", "project_revision_models"]
