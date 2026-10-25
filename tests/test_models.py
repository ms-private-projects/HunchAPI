"""The four Phase 0 tables follow the ms-markets extension conventions."""

from __future__ import annotations

import uuid

from hunch.migrations import PROJECT_TABLE_NAMES, all_project_metatable_models
from hunch.portfolios import HunchPortfolio, HunchPortfolioTable
from hunch.profiles import (
    HunchUserProfile,
    HunchUserProfileAccount,
    HunchUserProfileAccountTable,
    HunchUserProfileTable,
)
from hunch.takes import Take, TakeTable
from msm.models import AccountTable, PortfolioTable
from msm_portfolios.models import SignalMetadataTable


def _foreign_keys(table) -> dict[str, tuple[str, str | None]]:
    return {
        fk.parent.name: (fk.column.table.name + "." + fk.column.name, fk.ondelete)
        for fk in table.__table__.foreign_keys
    }


def test_project_tables_live_in_the_hunch_app_segment() -> None:
    assert PROJECT_TABLE_NAMES == {
        "hunch__user_profile",
        "hunch__user_profile_account",
        "hunch__instrument",
        "hunch__take",
        "hunch__take_revision",
        "hunch__portfolio",
        "hunch__funding",
        "hunch__rebalance_proposal",
        "hunch__daily_review",
        "hunch__leaderboard_snapshot",
        "hunch__notification",
    }
    for model in all_project_metatable_models():
        assert model.__table__.info["markets_storage_app"] == "hunch"
        assert model.__table__.info["namespace"] == "mainsequence.markets"


def test_user_profile_is_keyed_by_the_main_sequence_user_and_is_not_an_account() -> None:
    table = HunchUserProfileTable.__table__
    assert [column.name for column in table.primary_key.columns] == ["user_uid"]
    assert not _foreign_keys(HunchUserProfileTable)
    assert HunchUserProfile.__upsert_keys__ == ("user_uid",)


def test_profile_accounts_link_a_user_to_connector_created_accounts() -> None:
    foreign_keys = _foreign_keys(HunchUserProfileAccountTable)
    assert foreign_keys["user_uid"] == ("hunch__user_profile.user_uid", "CASCADE")
    assert foreign_keys["account_uid"] == (AccountTable.__table__.name + ".uid", "RESTRICT")
    unique = {
        tuple(column.name for column in index.columns)
        for index in HunchUserProfileAccountTable.__table__.indexes
        if index.unique
    }
    assert ("account_uid",) in unique, "one connector account links to one Hunch user"
    assert HunchUserProfileAccount.__upsert_keys__ == ("account_uid",)


def test_take_belongs_to_a_profile_and_carries_fork_lineage() -> None:
    foreign_keys = _foreign_keys(TakeTable)
    assert foreign_keys["owner_user_uid"] == ("hunch__user_profile.user_uid", "CASCADE")
    # Lineage columns are indexed UUIDs without a foreign key: the ms-markets runtime orders
    # MetaTables by their foreign-key graph and rejects a self-reference as a cycle.
    assert "forked_from_take_uid" not in foreign_keys
    assert "origin_take_uid" not in foreign_keys
    assert {"forked_from_take_uid", "origin_take_uid"} <= set(TakeTable.__table__.c.keys())
    assert foreign_keys["signal_uid"] == (
        SignalMetadataTable.__table__.name + ".signal_uid",
        "SET NULL",
    )
    take = Take(uid=uuid.uuid4(), owner_user_uid="user-1", title="t", thesis_text="x")
    assert (take.status, take.execution_mode, take.visibility) == ("draft", "practice", "private")


def test_hunch_portfolio_extends_the_ms_markets_portfolio_one_to_one() -> None:
    table = HunchPortfolioTable.__table__
    assert [column.name for column in table.primary_key.columns] == ["portfolio_uid"]
    foreign_keys = _foreign_keys(HunchPortfolioTable)
    assert foreign_keys["portfolio_uid"] == (PortfolioTable.__table__.name + ".uid", "CASCADE")
    assert foreign_keys["take_uid"] == ("hunch__take.uid", "CASCADE")
    assert foreign_keys["owner_user_uid"] == ("hunch__user_profile.user_uid", "RESTRICT")
    assert "uid" not in table.c, "one-to-one detail tables take the base uid as primary key"
    row = HunchPortfolio.model_validate(
        {"portfolio_uid": uuid.uuid4(), "take_uid": uuid.uuid4(), "owner_user_uid": "user-1"}
    )
    assert row.uid == row.portfolio_uid
    assert row.is_simulated is True
