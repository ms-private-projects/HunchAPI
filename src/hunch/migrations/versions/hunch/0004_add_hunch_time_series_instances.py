"""add the hunch time-series instances

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27 22:00:00.000000

Hunch's own instances of the ms-markets time-series contracts, in the ``hunch`` namespace (ADR
0006): the take graph's portfolio values, weights, signal weights, rebalance state and calendar
events; the daily bars; each funded take's fund holdings and target positions; and the simulated
venue's account holdings and fills. Every instance keeps the core contract's columns,
index and foreign keys to the Markets registries. The product tables keep their schema; the
migration Job moves their catalog entries to ``hunch`` before this revision runs.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hunch__accountholdingsts__simulated",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_uid", sa.Uuid(), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("holdings_set_uid", sa.Uuid(), nullable=False),
        sa.Column("is_trade_snapshot", sa.Boolean(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("direction", sa.SmallInteger(), nullable=False),
        sa.Column("target_trade_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_uid"],
            ["ms_markets__account.uid"],
            name=op.f("fk__hunch__accountholdingsts__simulated__account_uid_06ec026f1a"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__accountholdingsts__simulated__asset_ident_e62e84860b"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["holdings_set_uid"],
            ["ms_markets__accountholdingsset.uid"],
            name=op.f("fk__hunch__accountholdingsts__simulated__holdings_se_da651ee9ed"),
            ondelete="CASCADE",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.AccountHoldingsTS.simulated",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__accountholdingsts__simulated", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__accountholdingsts__simulated__time_index_31f3fa7a12",
            ["time_index", "account_uid", "asset_identifier"],
            unique=True,
        )

    op.create_table(
        "hunch__externalpricests__daily",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("trade_count", sa.Float(), nullable=True),
        sa.Column("vwap", sa.Float(), nullable=True),
        sa.Column("interpolated", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__externalpricests__daily__asset_identifier_54e1314843"),
            ondelete="RESTRICT",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.ExternalPricesTS.daily",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__externalpricests__daily", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__externalpricests__daily__time_index__ass_2638522360",
            ["time_index", "asset_identifier"],
            unique=True,
        )

    op.create_table(
        "hunch__portfoliocalendareventsts__takes",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calendar_identifier", sa.String(length=255), nullable=False),
        sa.Column("session_label", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("local_date", sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(
            ["calendar_identifier"],
            ["ms_markets__calendar.unique_identifier"],
            name=op.f("fk__hunch__portfoliocalendareventsts__takes__calenda_3145ebe5d2"),
            ondelete="RESTRICT",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.PortfolioCalendarEventsTS.takes",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__portfoliocalendareventsts__takes", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__portfoliocalendareventsts__takes__time_i_c0cb9cd845",
            ["time_index", "calendar_identifier", "session_label", "event_type"],
            unique=True,
        )

    op.create_table(
        "hunch__portfoliorebalancestatets__takes",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("portfolio_identifier", sa.String(length=255), nullable=False),
        sa.Column("rebalance_intent_id", sa.String(length=64), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("target_signal_time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_source", sa.String(length=255), nullable=False),
        sa.Column("execution_status", sa.String(length=32), nullable=False),
        sa.Column("target_weight", sa.Float(), nullable=False),
        sa.Column("weight_before", sa.Float(), nullable=False),
        sa.Column("weight_after", sa.Float(), nullable=False),
        sa.Column("executed_weight_delta", sa.Float(), nullable=False),
        sa.Column("remaining_weight_delta", sa.Float(), nullable=False),
        sa.Column("execution_price", sa.Float(), nullable=True),
        sa.Column("executed_quantity", sa.Float(), nullable=True),
        sa.Column("executed_notional", sa.Float(), nullable=True),
        sa.Column("observed_volume", sa.Float(), nullable=True),
        sa.Column("observed_available_liquidity", sa.Float(), nullable=True),
        sa.Column("strategy_state", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__portfoliorebalancestatets__takes__asset_i_32ae3a09a0"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_identifier"],
            ["ms_markets__portfolio.unique_identifier"],
            name=op.f("fk__hunch__portfoliorebalancestatets__takes__portfol_ea2d2ffb5e"),
            ondelete="RESTRICT",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.PortfolioRebalanceStateTS.takes",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__portfoliorebalancestatets__takes", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__portfoliorebalancestatets__takes__time_i_2fa3a9fb9d",
            ["time_index", "portfolio_identifier", "rebalance_intent_id", "asset_identifier"],
            unique=True,
        )

    op.create_table(
        "hunch__portfoliosts__takes",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("portfolio_identifier", sa.String(length=255), nullable=False),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("return", sa.Float(), nullable=True),
        sa.Column("calculated_close", sa.Float(), nullable=True),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_identifier"],
            ["ms_markets__portfolio.unique_identifier"],
            name=op.f("fk__hunch__portfoliosts__takes__portfolio_identifier_a082b08153"),
            ondelete="RESTRICT",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.PortfoliosTS.takes",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__portfoliosts__takes", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__portfoliosts__takes__time_index__portfol_c3bba0d924",
            ["time_index", "portfolio_identifier"],
            unique=True,
        )

    op.create_table(
        "hunch__portfolioweightsts__takes",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("portfolio_identifier", sa.String(length=255), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("weight_before", sa.Float(), nullable=True),
        sa.Column("price_current", sa.Float(), nullable=True),
        sa.Column("price_before", sa.Float(), nullable=True),
        sa.Column("volume_current", sa.Float(), nullable=True),
        sa.Column("volume_before", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__portfolioweightsts__takes__asset_identifi_0d3d10d74e"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_identifier"],
            ["ms_markets__portfolio.unique_identifier"],
            name=op.f("fk__hunch__portfolioweightsts__takes__portfolio_iden_333439264b"),
            ondelete="RESTRICT",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.PortfolioWeightsTS.takes",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__portfolioweightsts__takes", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__portfolioweightsts__takes__time_index__p_18190c7ec2",
            ["time_index", "portfolio_identifier", "asset_identifier"],
            unique=True,
        )

    op.create_table(
        "hunch__signalweightsts__takes",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_uid", sa.String(length=255), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("signal_weight", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__signalweightsts__takes__asset_identifier_191f3ecbb7"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["signal_uid"],
            ["ms_markets__signalmetadata.signal_uid"],
            name=op.f("fk__hunch__signalweightsts__takes__signal_uid__ms_ma_6da6f8d1c0"),
            ondelete="RESTRICT",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.SignalWeightsTS.takes",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__signalweightsts__takes", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__signalweightsts__takes__time_index__sign_7be054376c",
            ["time_index", "signal_uid", "asset_identifier"],
            unique=True,
        )

    op.create_table(
        "hunch__targetpositionsts__takes",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("position_set_uid", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_uid", sa.Uuid(), nullable=False),
        sa.Column("asset_uid", sa.Uuid(), nullable=True),
        sa.Column("portfolio_uid", sa.Uuid(), nullable=True),
        sa.Column("weight_notional_exposure", sa.Float(), nullable=True),
        sa.Column("constant_notional_exposure", sa.Float(), nullable=True),
        sa.Column("single_asset_quantity", sa.Float(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_uid"],
            ["ms_markets__asset.uid"],
            name=op.f("fk__hunch__targetpositionsts__takes__asset_uid__ms_m_144b8ec060"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_uid"],
            ["ms_markets__portfolio.uid"],
            name=op.f("fk__hunch__targetpositionsts__takes__portfolio_uid_ac34f5f702"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_set_uid"],
            ["ms_markets__positionset.uid"],
            name=op.f("fk__hunch__targetpositionsts__takes__position_set_ui_525a574d3e"),
            ondelete="CASCADE",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.TargetPositionsTS.takes",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__targetpositionsts__takes", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__targetpositionsts__takes__time_index__po_58d9147a87",
            ["time_index", "position_set_uid", "target_type", "target_uid"],
            unique=True,
        )

    op.create_table(
        "hunch__tradests__simulated",
        sa.Column("trade_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trade_identifier", sa.String(), nullable=False),
        sa.Column("account_identifier", sa.String(length=255), nullable=False),
        sa.Column("order_identifier", sa.String(), nullable=True),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("trade_side", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("commission", sa.Float(), nullable=True),
        sa.Column("commission_asset_identifier", sa.String(length=255), nullable=True),
        sa.Column("settlement_cost", sa.Float(), nullable=True),
        sa.Column("settlement_asset_identifier", sa.String(length=255), nullable=True),
        sa.Column("comments", sa.String(), nullable=True),
        sa.Column("venue_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_identifier"],
            ["ms_markets__account.unique_identifier"],
            name=op.f("fk__hunch__tradests__simulated__account_identifier_f552b0a2cf"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__tradests__simulated__asset_identifier__ms_fd28494854"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["commission_asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__tradests__simulated__commission_asset_ide_6c11842fdb"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["settlement_asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__tradests__simulated__settlement_asset_ide_8f8259fbf6"),
            ondelete="RESTRICT",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.TradesTS.simulated",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__tradests__simulated", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__tradests__simulated__trade_time__trade_i_22fd7aaf22",
            ["trade_time", "trade_identifier", "account_identifier", "asset_identifier"],
            unique=True,
        )

    op.create_table(
        "hunch__virtualfundholdingsts__takes",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("virtual_fund_uid", sa.Uuid(), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("virtual_fund_holdings_set_uid", sa.Uuid(), nullable=False),
        sa.Column("source_account_holdings_set_uid", sa.Uuid(), nullable=False),
        sa.Column("allocated_quantity", sa.Float(), nullable=False),
        sa.Column("allocation_strategy", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.SmallInteger(), nullable=False),
        sa.Column("target_trade_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__hunch__virtualfundholdingsts__takes__asset_ident_866ce513be"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_account_holdings_set_uid"],
            ["ms_markets__accountholdingsset.uid"],
            name=op.f("fk__hunch__virtualfundholdingsts__takes__source_acco_9212be15ed"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["virtual_fund_holdings_set_uid"],
            ["ms_markets__virtualfundholdingsset.uid"],
            name=op.f("fk__hunch__virtualfundholdingsts__takes__virtual_fun_238662ba39"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["virtual_fund_uid"],
            ["ms_markets__virtualfund.uid"],
            name=op.f("fk__hunch__virtualfundholdingsts__takes__virtual_fun_73bc11a9da"),
            ondelete="CASCADE",
        ),
        info={
            "namespace": "hunch",
            "identifier": "hunch.VirtualFundHoldingsTS.takes",
            "markets_storage_app": "hunch",
        },
    )
    with op.batch_alter_table("hunch__virtualfundholdingsts__takes", schema=None) as batch_op:
        batch_op.create_index(
            "uix__hunch__virtualfundholdingsts__takes__time_index_ab6fed9485",
            ["time_index", "virtual_fund_uid", "asset_identifier"],
            unique=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("hunch__virtualfundholdingsts__takes", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__virtualfundholdingsts__takes__time_index_ab6fed9485")

    op.drop_table("hunch__virtualfundholdingsts__takes")
    with op.batch_alter_table("hunch__tradests__simulated", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__tradests__simulated__trade_time__trade_i_22fd7aaf22")

    op.drop_table("hunch__tradests__simulated")
    with op.batch_alter_table("hunch__targetpositionsts__takes", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__targetpositionsts__takes__time_index__po_58d9147a87")

    op.drop_table("hunch__targetpositionsts__takes")
    with op.batch_alter_table("hunch__signalweightsts__takes", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__signalweightsts__takes__time_index__sign_7be054376c")

    op.drop_table("hunch__signalweightsts__takes")
    with op.batch_alter_table("hunch__portfolioweightsts__takes", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__portfolioweightsts__takes__time_index__p_18190c7ec2")

    op.drop_table("hunch__portfolioweightsts__takes")
    with op.batch_alter_table("hunch__portfoliosts__takes", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__portfoliosts__takes__time_index__portfol_c3bba0d924")

    op.drop_table("hunch__portfoliosts__takes")
    with op.batch_alter_table("hunch__portfoliorebalancestatets__takes", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__portfoliorebalancestatets__takes__time_i_2fa3a9fb9d")

    op.drop_table("hunch__portfoliorebalancestatets__takes")
    with op.batch_alter_table("hunch__portfoliocalendareventsts__takes", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__portfoliocalendareventsts__takes__time_i_c0cb9cd845")

    op.drop_table("hunch__portfoliocalendareventsts__takes")
    with op.batch_alter_table("hunch__externalpricests__daily", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__externalpricests__daily__time_index__ass_2638522360")

    op.drop_table("hunch__externalpricests__daily")
    with op.batch_alter_table("hunch__accountholdingsts__simulated", schema=None) as batch_op:
        batch_op.drop_index("uix__hunch__accountholdingsts__simulated__time_index_31f3fa7a12")

    op.drop_table("hunch__accountholdingsts__simulated")
