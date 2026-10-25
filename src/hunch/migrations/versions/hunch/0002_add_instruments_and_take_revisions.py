"""add instruments and take revisions

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25 09:00:00.000000

The venue-neutral instrument universe (FIGI keyed, pointing at the canonical ms-markets Asset)
and the basket revisions of a take.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAMESPACE = "mainsequence.markets"
_APP = "hunch"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hunch__instrument",
        sa.Column("figi", sa.String(length=12), nullable=False),
        sa.Column("asset_uid", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("exchange_code", sa.String(length=16), nullable=True),
        sa.Column("security_type", sa.String(length=64), nullable=True),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("themes_json", sa.JSON(), nullable=True),
        sa.Column("is_etf", sa.Boolean(), nullable=False),
        sa.Column("is_leveraged", sa.Boolean(), nullable=False),
        sa.Column("is_inverse", sa.Boolean(), nullable=False),
        sa.Column("is_tradable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_uid"],
            ["ms_markets__asset.uid"],
            name=op.f("fk__hunch__instrument__asset_uid__ms_markets__asset__uid"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("figi", name=op.f("pk__hunch__instrument")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchInstrument",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(op.f("ix__hunch__instrument__sector"), "hunch__instrument", ["sector"])
    op.create_index(op.f("ix__hunch__instrument__ticker"), "hunch__instrument", ["ticker"])
    op.create_index(
        op.f("uix__hunch__instrument__asset_uid"), "hunch__instrument", ["asset_uid"], unique=True
    )

    op.create_table(
        "hunch__take_revision",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("take_uid", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("rationale_md", sa.Text(), nullable=False),
        sa.Column("weights_json", sa.JSON(), nullable=False),
        sa.Column("research_json", sa.JSON(), nullable=True),
        sa.Column("inference_request_uids", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("signal_time_index", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__take_revision__take_uid__hunch__take__uid"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__take_revision")),
        info={
            "namespace": _NAMESPACE,
            "identifier": "HunchTakeRevision",
            "markets_storage_app": _APP,
        },
    )
    op.create_index(
        op.f("uix__hunch__take_revision__take_uid__revision"),
        "hunch__take_revision",
        ["take_uid", "revision"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("uix__hunch__take_revision__take_uid__revision"), table_name="hunch__take_revision"
    )
    op.drop_table("hunch__take_revision")
    op.drop_index(op.f("uix__hunch__instrument__asset_uid"), table_name="hunch__instrument")
    op.drop_index(op.f("ix__hunch__instrument__ticker"), table_name="hunch__instrument")
    op.drop_index(op.f("ix__hunch__instrument__sector"), table_name="hunch__instrument")
    op.drop_table("hunch__instrument")
