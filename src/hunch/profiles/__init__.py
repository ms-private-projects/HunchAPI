"""Hunch users and the venue accounts linked to them.

A ``HunchUserProfile`` is the Hunch user, keyed by the Main Sequence user UID. It is **not** an
ms-markets ``Account``: it owns takes and links, one-to-many, to the ``Account`` rows that the
venue connectors (Alpaca, IBKR) create for that person. ms-markets rows carry no owner, so these
two tables are where Hunch decides who may see and act on a brokerage account.

Credentials never appear here. A link records the connector-created ``Account`` and its status;
the connector keeps the broker keys.
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
from hunch.settings import PROJECT_NAMESPACE_SLUG
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args, new_markets_uid
from msm.models import AccountTable

UTC = dt.timezone.utc


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC).replace(microsecond=0)


class HunchUserProfileTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per Hunch user, keyed by the Main Sequence user UID."""

    __project_storage_concept__ = "user_profile"
    __markets_base_identifier__ = "HunchUserProfile"
    __metatable_description__ = (
        "One row per Hunch user: the Main Sequence user who writes takes and links brokerage "
        "accounts. Public handle and display name for attribution on shared takes and the "
        "leaderboard. This is the product user, not an ms-markets Account."
    )
    __metatable_labels__ = ["hunch", "users", "profiles"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_user_profile",
    }
    __table_args__ = markets_table_args(
        "HunchUserProfile",
        Index(None, "handle", unique=True),
    )

    user_uid: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        nullable=False,
        info={
            "label": "User UID",
            "description": "Main Sequence user UID of the person; the request identity supplies it.",
        },
    )
    handle: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Handle",
            "description": "Public, unique handle shown on published takes and the leaderboard.",
        },
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={"label": "Display name", "description": "Optional public display name."},
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        info={"label": "Created at", "description": "When the profile was created (UTC)."},
    )
    # Services set updated_at explicitly: a Python-side `onupdate` default does not travel
    # through the MetaTables compiled-SQL update path.
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        info={"label": "Updated at", "description": "When the profile last changed (UTC)."},
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Free-form product preferences; never credentials or identifiers of others.",
        },
    )


class HunchUserProfileAccountTable(
    ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase
):
    """One venue account linked to one Hunch user."""

    __project_storage_concept__ = "user_profile_account"
    __markets_base_identifier__ = "HunchUserProfileAccount"
    __metatable_description__ = (
        "One row per brokerage account linked to a Hunch user: the venue (alpaca, ibkr), the "
        "ms-markets Account the venue connector created, paper or live, and the link status "
        "(pending, active, revoked). The ownership that ms-markets Accounts do not carry. No "
        "credential or Secret reference is stored here."
    )
    __metatable_labels__ = ["hunch", "users", "accounts", "brokerage"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_user_profile_account",
    }
    __table_args__ = markets_table_args(
        "HunchUserProfileAccount",
        Index(None, "account_uid", unique=True),
        Index(None, "user_uid"),
        Index(None, "status"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={"label": "UID", "description": "Public UUID of the account link."},
    )
    user_uid: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{HunchUserProfileTable.__table__.fullname}.user_uid", ondelete="CASCADE"),
        nullable=False,
        info={"label": "User UID", "description": "The Hunch user who owns this link."},
    )
    venue: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Venue",
            "description": "Brokerage connector the account belongs to: alpaca or ibkr.",
        },
    )
    account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{AccountTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=False,
        info={
            "label": "Account UID",
            "description": "ms-markets Account the venue connector created and refreshes.",
        },
    )
    is_paper: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        info={"label": "Paper", "description": "True for a paper account at the venue."},
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        info={"label": "Status", "description": "pending, active or revoked."},
    )
    linked_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        info={"label": "Linked at", "description": "When the link was created (UTC)."},
    )
    activated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={"label": "Activated at", "description": "When ownership was verified (UTC)."},
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={"label": "Revoked at", "description": "When the person unlinked the account (UTC)."},
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Connector-side identifiers useful for display; never credentials.",
        },
    )


class HunchUserProfile(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchUserProfileTable``."""

    __table__: ClassVar[type[HunchUserProfileTable]] = HunchUserProfileTable
    __required_tables__: ClassVar[list[type[Any]]] = [HunchUserProfileTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("user_uid",)

    uid: str = Field(validation_alias=AliasChoices("uid", "user_uid"))
    user_uid: str
    handle: str
    display_name: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    metadata_json: dict[str, Any] | None = None


class HunchUserProfileAccount(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``HunchUserProfileAccountTable``."""

    __table__: ClassVar[type[HunchUserProfileAccountTable]] = HunchUserProfileAccountTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        HunchUserProfileTable,
        HunchUserProfileAccountTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("account_uid",)

    user_uid: str
    venue: str
    account_uid: uuid.UUID
    is_paper: bool = True
    status: str = "pending"
    linked_at: dt.datetime | None = None
    activated_at: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    metadata_json: dict[str, Any] | None = None


def project_profile_models() -> list[type[Any]]:
    """Project-owned MetaTables of this package, in dependency order."""
    return [HunchUserProfileTable, HunchUserProfileAccountTable]


__all__ = [
    "HunchUserProfile",
    "HunchUserProfileAccount",
    "HunchUserProfileAccountTable",
    "HunchUserProfileTable",
    "project_profile_models",
    "utc_now",
]
