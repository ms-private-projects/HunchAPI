"""create hunch profiles, takes and portfolios

Revision ID: 0001
Revises:
Create Date: 2026-10-25 12:00:00.000000

The four Phase 0 tables of the `hunch` namespace. Constraint and index names are the ones the
ms-markets naming convention derives from the models in `hunch.profiles`, `hunch.takes` and
`hunch.portfolios`; the referenced ms-markets tables are owned by the ms-markets deployment.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAMESPACE = "mainsequence.markets"
_APP = "hunch"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hunch__user_profile",
        sa.Column("user_uid", sa.String(length=255), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("user_uid", name=op.f("pk__hunch__user_profile")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchUserProfile",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(
        op.f("uix__hunch__user_profile__handle"),
        "hunch__user_profile",
        ["handle"],
        unique=True,
    )

    op.create_table(
        "hunch__take",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("owner_user_uid", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("thesis_text", sa.Text(), nullable=False),
        sa.Column("constraints_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("forked_from_take_uid", sa.Uuid(), nullable=True),
        sa.Column("origin_take_uid", sa.Uuid(), nullable=True),
        sa.Column("signal_uid", sa.String(length=255), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_uid"],
            ["hunch__user_profile.user_uid"],
            name=op.f("fk__hunch__take__owner_user_uid__hunch__user_profile__user_uid"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_uid"],
            ["ms_markets__signalmetadata.signal_uid"],
            name=op.f("fk__hunch__take__signal_uid__ms_markets__signalmetad_ca2ae6bfb7"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["forked_from_take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__take__forked_from_take_uid__hunch__take__uid"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["origin_take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__take__origin_take_uid__hunch__take__uid"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__take")),
        info={"namespace": _NAMESPACE, "identifier": "HunchTake", "markets_storage_app": _APP},
    )
    op.create_index(op.f("ix__hunch__take__origin_take_uid"), "hunch__take", ["origin_take_uid"])
    op.create_index(op.f("ix__hunch__take__owner_user_uid"), "hunch__take", ["owner_user_uid"])
    op.create_index(op.f("ix__hunch__take__status"), "hunch__take", ["status"])
    op.create_index(op.f("ix__hunch__take__visibility"), "hunch__take", ["visibility"])

    op.create_table(
        "hunch__user_profile_account",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("user_uid", sa.String(length=255), nullable=False),
        sa.Column("venue", sa.String(length=32), nullable=False),
        sa.Column("account_uid", sa.Uuid(), nullable=False),
        sa.Column("is_paper", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_uid"],
            ["hunch__user_profile.user_uid"],
            name=op.f("fk__hunch__user_profile_account__user_uid__hunch__us_ccc3203d61"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_uid"],
            ["ms_markets__account.uid"],
            name=op.f("fk__hunch__user_profile_account__account_uid__ms_mar_fbe2c8e99f"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__user_profile_account")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchUserProfileAccount",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(
        op.f("ix__hunch__user_profile_account__status"),
        "hunch__user_profile_account",
        ["status"],
    )
    op.create_index(
        op.f("ix__hunch__user_profile_account__user_uid"),
        "hunch__user_profile_account",
        ["user_uid"],
    )
    op.create_index(
        op.f("uix__hunch__user_profile_account__account_uid"),
        "hunch__user_profile_account",
        ["account_uid"],
        unique=True,
    )

    op.create_table(
        "hunch__portfolio",
        sa.Column("portfolio_uid", sa.Uuid(), nullable=False),
        sa.Column("take_uid", sa.Uuid(), nullable=False),
        sa.Column("owner_user_uid", sa.String(length=255), nullable=False),
        sa.Column("basket_revision", sa.Integer(), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_uid"],
            ["ms_markets__portfolio.uid"],
            name=op.f("fk__hunch__portfolio__portfolio_uid__ms_markets__portfolio__uid"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__portfolio__take_uid__hunch__take__uid"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_uid"],
            ["hunch__user_profile.user_uid"],
            name=op.f("fk__hunch__portfolio__owner_user_uid__hunch__user_pr_41c93812c5"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("portfolio_uid", name=op.f("pk__hunch__portfolio")),
        info={"namespace": _NAMESPACE, "identifier": "HunchPortfolio", "markets_storage_app": _APP},
    )
    op.create_index(
        op.f("ix__hunch__portfolio__owner_user_uid"), "hunch__portfolio", ["owner_user_uid"]
    )
    op.create_index(
        op.f("uix__hunch__portfolio__take_uid"), "hunch__portfolio", ["take_uid"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("uix__hunch__portfolio__take_uid"), table_name="hunch__portfolio")
    op.drop_index(op.f("ix__hunch__portfolio__owner_user_uid"), table_name="hunch__portfolio")
    op.drop_table("hunch__portfolio")
    op.drop_index(
        op.f("uix__hunch__user_profile_account__account_uid"),
        table_name="hunch__user_profile_account",
    )
    op.drop_index(
        op.f("ix__hunch__user_profile_account__user_uid"), table_name="hunch__user_profile_account"
    )
    op.drop_index(
        op.f("ix__hunch__user_profile_account__status"), table_name="hunch__user_profile_account"
    )
    op.drop_table("hunch__user_profile_account")
    op.drop_index(op.f("ix__hunch__take__visibility"), table_name="hunch__take")
    op.drop_index(op.f("ix__hunch__take__status"), table_name="hunch__take")
    op.drop_index(op.f("ix__hunch__take__owner_user_uid"), table_name="hunch__take")
    op.drop_index(op.f("ix__hunch__take__origin_take_uid"), table_name="hunch__take")
    op.drop_table("hunch__take")
    op.drop_index(op.f("uix__hunch__user_profile__handle"), table_name="hunch__user_profile")
    op.drop_table("hunch__user_profile")
