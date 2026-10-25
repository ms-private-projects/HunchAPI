"""add funding, proposals, daily reviews, leaderboard and notifications

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25 10:00:00.000000

Funded takes (one linked venue account each, backed by an ms-markets VirtualFund), the rebalance
proposals that drive approvals and autopilot (linked to the OrderManager batch the connector
executes), the daily review audit, the nightly leaderboard and the notification feed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAMESPACE = "mainsequence.markets"
_APP = "hunch"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hunch__funding",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("take_uid", sa.Uuid(), nullable=False),
        sa.Column("owner_user_uid", sa.String(length=255), nullable=False),
        sa.Column("profile_account_uid", sa.Uuid(), nullable=False),
        sa.Column("venue", sa.String(length=16), nullable=False),
        sa.Column("virtual_fund_uid", sa.Uuid(), nullable=True),
        sa.Column("target_notional", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("autopilot_policy_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["virtual_fund_uid"],
            ["ms_markets__virtualfund.uid"],
            name=op.f("fk__hunch__funding__virtual_fund_uid__ms_markets__vi_ec06830e5d"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["profile_account_uid"],
            ["hunch__user_profile_account.uid"],
            name=op.f("fk__hunch__funding__profile_account_uid__hunch__user_31a316b8fc"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_uid"],
            ["hunch__user_profile.user_uid"],
            name=op.f("fk__hunch__funding__owner_user_uid__hunch__user_prof_f78739f2a7"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__funding__take_uid__hunch__take__uid"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__funding")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchFunding",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(
        op.f("ix__hunch__funding__owner_user_uid"), "hunch__funding", ["owner_user_uid"]
    )
    op.create_index(
        op.f("ix__hunch__funding__profile_account_uid"), "hunch__funding", ["profile_account_uid"]
    )
    op.create_index(op.f("ix__hunch__funding__status"), "hunch__funding", ["status"])
    op.create_index(
        op.f("uix__hunch__funding__take_uid"), "hunch__funding", ["take_uid"], unique=True
    )
    op.create_index(
        op.f("uix__hunch__funding__virtual_fund_uid"),
        "hunch__funding",
        ["virtual_fund_uid"],
        unique=True,
    )
    op.create_table(
        "hunch__rebalance_proposal",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("take_uid", sa.Uuid(), nullable=False),
        sa.Column("funding_uid", sa.Uuid(), nullable=False),
        sa.Column("owner_user_uid", sa.String(length=255), nullable=False),
        sa.Column("revision_uid", sa.Uuid(), nullable=True),
        sa.Column("order_manager_uid", sa.Uuid(), nullable=True),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("legs_json", sa.JSON(), nullable=False),
        sa.Column("summary_md", sa.Text(), nullable=False),
        sa.Column("autopilot_check_json", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_uid", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["order_manager_uid"],
            ["ms_markets__ordermanager.uid"],
            name=op.f("fk__hunch__rebalance_proposal__order_manager_uid__ms_f4cdbafd64"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_uid"],
            ["hunch__user_profile.user_uid"],
            name=op.f("fk__hunch__rebalance_proposal__owner_user_uid__hunch_9c17fbee4c"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__rebalance_proposal__take_uid__hunch__take__uid"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_uid"],
            ["hunch__take_revision.uid"],
            name=op.f("fk__hunch__rebalance_proposal__revision_uid__hunch_83c67cf6c5"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["funding_uid"],
            ["hunch__funding.uid"],
            name=op.f("fk__hunch__rebalance_proposal__funding_uid__hunch__funding__uid"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__rebalance_proposal")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchRebalanceProposal",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(
        op.f("ix__hunch__rebalance_proposal__created_at"),
        "hunch__rebalance_proposal",
        ["created_at"],
    )
    op.create_index(
        op.f("ix__hunch__rebalance_proposal__funding_uid"),
        "hunch__rebalance_proposal",
        ["funding_uid"],
    )
    op.create_index(
        op.f("ix__hunch__rebalance_proposal__owner_user_uid"),
        "hunch__rebalance_proposal",
        ["owner_user_uid"],
    )
    op.create_index(
        op.f("ix__hunch__rebalance_proposal__status"), "hunch__rebalance_proposal", ["status"]
    )
    op.create_index(
        op.f("ix__hunch__rebalance_proposal__take_uid"), "hunch__rebalance_proposal", ["take_uid"]
    )
    op.create_table(
        "hunch__daily_review",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("take_uid", sa.Uuid(), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column("drift_json", sa.JSON(), nullable=True),
        sa.Column("thesis_check_json", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("proposal_uid", sa.Uuid(), nullable=True),
        sa.Column("inference_request_uids", sa.JSON(), nullable=True),
        sa.Column("summary_md", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["proposal_uid"],
            ["hunch__rebalance_proposal.uid"],
            name=op.f("fk__hunch__daily_review__proposal_uid__hunch__rebala_1cd55928da"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__daily_review__take_uid__hunch__take__uid"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__daily_review")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchDailyReview",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(
        op.f("ix__hunch__daily_review__review_date"), "hunch__daily_review", ["review_date"]
    )
    op.create_index(
        op.f("uix__hunch__daily_review__take_uid__review_date"),
        "hunch__daily_review",
        ["take_uid", "review_date"],
        unique=True,
    )
    op.create_table(
        "hunch__leaderboard_snapshot",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("take_uid", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("return_since_activation", sa.Float(), nullable=False),
        sa.Column("days_active", sa.Integer(), nullable=False),
        sa.Column("value_points", sa.Integer(), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column("is_funded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__leaderboard_snapshot__take_uid__hunch__take__uid"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__leaderboard_snapshot")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchLeaderboardSnapshot",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(
        op.f("ix__hunch__leaderboard_snapshot__snapshot_date__rank"),
        "hunch__leaderboard_snapshot",
        ["snapshot_date", "rank"],
    )
    op.create_index(
        op.f("uix__hunch__leaderboard_snapshot__snapshot_date__take_uid"),
        "hunch__leaderboard_snapshot",
        ["snapshot_date", "take_uid"],
        unique=True,
    )
    op.create_table(
        "hunch__notification",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("user_uid", sa.String(length=255), nullable=False),
        sa.Column("take_uid", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_channels_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_uid"],
            ["hunch__user_profile.user_uid"],
            name=op.f("fk__hunch__notification__user_uid__hunch__user_profi_c354d8bacd"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__notification__take_uid__hunch__take__uid"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__notification")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchNotification",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(op.f("ix__hunch__notification__take_uid"), "hunch__notification", ["take_uid"])
    op.create_index(
        op.f("ix__hunch__notification__user_uid__created_at"),
        "hunch__notification",
        ["user_uid", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix__hunch__notification__take_uid"), table_name="hunch__notification")
    op.drop_index(
        op.f("ix__hunch__notification__user_uid__created_at"), table_name="hunch__notification"
    )
    op.drop_table("hunch__notification")
    op.drop_index(
        op.f("ix__hunch__leaderboard_snapshot__snapshot_date__rank"),
        table_name="hunch__leaderboard_snapshot",
    )
    op.drop_index(
        op.f("uix__hunch__leaderboard_snapshot__snapshot_date__take_uid"),
        table_name="hunch__leaderboard_snapshot",
    )
    op.drop_table("hunch__leaderboard_snapshot")
    op.drop_index(op.f("ix__hunch__daily_review__review_date"), table_name="hunch__daily_review")
    op.drop_index(
        op.f("uix__hunch__daily_review__take_uid__review_date"), table_name="hunch__daily_review"
    )
    op.drop_table("hunch__daily_review")
    op.drop_index(
        op.f("ix__hunch__rebalance_proposal__created_at"), table_name="hunch__rebalance_proposal"
    )
    op.drop_index(
        op.f("ix__hunch__rebalance_proposal__funding_uid"), table_name="hunch__rebalance_proposal"
    )
    op.drop_index(
        op.f("ix__hunch__rebalance_proposal__owner_user_uid"),
        table_name="hunch__rebalance_proposal",
    )
    op.drop_index(
        op.f("ix__hunch__rebalance_proposal__status"), table_name="hunch__rebalance_proposal"
    )
    op.drop_index(
        op.f("ix__hunch__rebalance_proposal__take_uid"), table_name="hunch__rebalance_proposal"
    )
    op.drop_table("hunch__rebalance_proposal")
    op.drop_index(op.f("ix__hunch__funding__owner_user_uid"), table_name="hunch__funding")
    op.drop_index(op.f("ix__hunch__funding__profile_account_uid"), table_name="hunch__funding")
    op.drop_index(op.f("ix__hunch__funding__status"), table_name="hunch__funding")
    op.drop_index(op.f("uix__hunch__funding__take_uid"), table_name="hunch__funding")
    op.drop_index(op.f("uix__hunch__funding__virtual_fund_uid"), table_name="hunch__funding")
    op.drop_table("hunch__funding")
