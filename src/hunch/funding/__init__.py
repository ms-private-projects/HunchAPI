"""Funded takes and their rebalance proposals.

A ``HunchFunding`` ties one take to one linked venue account with a target notional; ms-markets
holds the money side (``VirtualFund``, holdings, target positions, the ``OrderManager`` batches).
A ``HunchRebalanceProposal`` is the approval and autopilot state machine: the legs Hunch computed,
who decided, when it was submitted and how it ended. Hunch never stores a broker credential or
talks to a brokerage directly; the venue connector executes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from hunch.metatables import HunchMarketsMetaTableMixin, ProjectStorageNameMixin
from hunch.profiles import HunchUserProfileAccountTable, HunchUserProfileTable, utc_now
from hunch.settings import PROJECT_NAMESPACE_SLUG
from hunch.takes import TakeTable
from hunch.takes.revisions import TakeRevisionTable
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args, new_markets_uid
from msm.models import OrderManagerTable, VirtualFundTable


class HunchFundingTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per funded take: the take, the linked venue account and the target notional."""

    __project_storage_concept__ = "funding"
    __markets_base_identifier__ = "HunchFunding"
    __metatable_description__ = (
        "A take funded into one linked venue account: the target notional, the ms-markets "
        "VirtualFund that tracks the position inside the account, the autopilot policy and the "
        "funding lifecycle (planned, pending_initial, active, withdrawing, closed, failed)."
    )
    __metatable_labels__ = ["hunch", "funding", "accounts"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_funding",
    }
    __table_args__ = markets_table_args(
        "HunchFunding",
        Index(None, "take_uid", unique=True),
        Index(None, "virtual_fund_uid", unique=True),
        Index(None, "owner_user_uid"),
        Index(None, "profile_account_uid"),
        Index(None, "status"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
    )
    take_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_uid: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{HunchUserProfileTable.__table__.fullname}.user_uid", ondelete="RESTRICT"),
        nullable=False,
    )
    profile_account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{HunchUserProfileAccountTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=False,
        info={"description": "The linked venue account the take is funded in."},
    )
    venue: Mapped[str] = mapped_column(String(16), nullable=False)
    virtual_fund_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{VirtualFundTable.__table__.fullname}.uid", ondelete="SET NULL"),
        nullable=True,
        info={"description": "The ms-markets VirtualFund (account x take portfolio)."},
    )
    target_notional: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="planned",
        info={"description": "planned, pending_initial, active, withdrawing, closed or failed."},
    )
    autopilot_policy_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "description": (
                "Server-enforced autopilot limits: max_turnover_per_day, max_notional_per_order, "
                "max_single_name_weight, allow_new_instruments, trading_window."
            )
        },
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    activated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class HunchRebalanceProposalTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per set of trades proposed for a funded take."""

    __project_storage_concept__ = "rebalance_proposal"
    __markets_base_identifier__ = "HunchRebalanceProposal"
    __metatable_description__ = (
        "A set of trades Hunch proposed for a funded take: the legs (instrument, side, quantity, "
        "estimated notional, reason), the trigger, the approval decision, the ms-markets "
        "OrderManager batch the connector executed and the outcome."
    )
    __metatable_labels__ = ["hunch", "funding", "execution", "approvals"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_rebalance_proposal",
    }
    __table_args__ = markets_table_args(
        "HunchRebalanceProposal",
        Index(None, "take_uid"),
        Index(None, "funding_uid"),
        Index(None, "owner_user_uid"),
        Index(None, "status"),
        Index(None, "created_at"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
    )
    take_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
    )
    funding_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{HunchFundingTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_uid: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{HunchUserProfileTable.__table__.fullname}.user_uid", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeRevisionTable.__table__.fullname}.uid", ondelete="SET NULL"),
        nullable=True,
        info={"description": "The basket revision the legs move the account towards."},
    )
    order_manager_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{OrderManagerTable.__table__.fullname}.uid", ondelete="SET NULL"),
        nullable=True,
        info={"description": "The ms-markets order batch once the proposal is submitted."},
    )
    trigger: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        info={"description": "initial, drift, thesis, user or withdrawal."},
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="proposed",
        info={
            "description": (
                "proposed, approved, rejected, expired, submitted, partially_filled, filled or "
                "failed."
            )
        },
    )
    legs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        info={
            "description": (
                "[{figi, ticker, side, quantity, estimated_price, estimated_notional, "
                "target_weight, current_weight, reason}]"
            )
        },
    )
    summary_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    autopilot_check_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_uid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class HunchFunding(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchFundingTable``."""

    __table__: ClassVar[type[HunchFundingTable]] = HunchFundingTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        HunchUserProfileTable,
        HunchUserProfileAccountTable,
        TakeTable,
        HunchFundingTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("take_uid",)

    take_uid: uuid.UUID
    owner_user_uid: str
    profile_account_uid: uuid.UUID
    venue: str
    virtual_fund_uid: uuid.UUID | None = None
    target_notional: float
    currency: str = "USD"
    status: str = "planned"
    autopilot_policy_json: dict[str, Any] | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    activated_at: dt.datetime | None = None
    closed_at: dt.datetime | None = None
    metadata_json: dict[str, Any] | None = None


class HunchRebalanceProposal(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchRebalanceProposalTable``."""

    __table__: ClassVar[type[HunchRebalanceProposalTable]] = HunchRebalanceProposalTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        HunchUserProfileTable,
        TakeTable,
        TakeRevisionTable,
        HunchFundingTable,
        HunchRebalanceProposalTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("uid",)

    take_uid: uuid.UUID
    funding_uid: uuid.UUID
    owner_user_uid: str
    revision_uid: uuid.UUID | None = None
    order_manager_uid: uuid.UUID | None = None
    trigger: str
    status: str = "proposed"
    legs_json: list[dict[str, Any]]
    summary_md: str = ""
    autopilot_check_json: dict[str, Any] | None = None
    expires_at: dt.datetime | None = None
    decided_by_user_uid: str | None = None
    decided_at: dt.datetime | None = None
    submitted_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    metadata_json: dict[str, Any] | None = None


def project_funding_models() -> list[type[Any]]:
    return [HunchFundingTable, HunchRebalanceProposalTable]


__all__ = [
    "HunchFunding",
    "HunchFundingTable",
    "HunchRebalanceProposal",
    "HunchRebalanceProposalTable",
    "project_funding_models",
]
