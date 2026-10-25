"""Synthetic bars, the trading schedule, the basket signal identity and the SQLite shims."""

from __future__ import annotations

import datetime as dt
import os
import uuid

import pandas as pd
import pytest

from hunch.compat import install_compat_patches
from hunch.market_data import (
    BAR_COLUMNS,
    SyntheticBarsProvider,
    last_completed_session_close,
    session_schedule,
)
from hunch.portfolios.services import hunch_portfolio_identifier
from hunch.portfolios.signal import basket_signal, basket_signal_uid


def test_synthetic_bars_are_deterministic_and_stamped_at_the_close() -> None:
    provider = SyntheticBarsProvider()
    first = provider.daily_bars(
        ["BBG000B9XRY4", "BBG000BPH459"], dt.date(2026, 1, 5), dt.date(2026, 1, 16)
    )
    second = provider.daily_bars(
        ["BBG000B9XRY4", "BBG000BPH459"], dt.date(2026, 1, 5), dt.date(2026, 1, 16)
    )
    pd.testing.assert_frame_equal(first, second)
    assert set(BAR_COLUMNS) <= set(first.columns)
    sessions = session_schedule(dt.date(2026, 1, 5), dt.date(2026, 1, 16))
    assert len(first) == 2 * len(sessions) and len(sessions) == 10
    closes = pd.to_datetime(first["time_index"]).dt.tz_convert("UTC")
    assert set(closes) == set(sessions["market_close"])
    assert (first["high"] >= first[["open", "close"]].max(axis=1)).all()
    assert (first["low"] <= first[["open", "close"]].min(axis=1)).all()
    # A longer range reproduces the shorter one's prefix: appended days never rewrite history.
    longer = provider.daily_bars(["BBG000B9XRY4"], dt.date(2026, 1, 5), dt.date(2026, 2, 27))
    short = first[first["asset_identifier"] == "BBG000B9XRY4"]
    assert longer["close"].iloc[: len(short)].tolist() == short["close"].tolist()


def test_last_completed_session_close_is_the_latest_close_at_or_before_now() -> None:
    saturday = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.timezone.utc)
    assert last_completed_session_close(saturday) == dt.datetime(
        2026, 10, 23, 20, 0, tzinfo=dt.timezone.utc
    )
    friday_midday = dt.datetime(2026, 10, 23, 15, 0, tzinfo=dt.timezone.utc)
    assert last_completed_session_close(friday_midday) == dt.datetime(
        2026, 10, 22, 20, 0, tzinfo=dt.timezone.utc
    )


def test_portfolio_identifier_is_derived_from_the_take() -> None:
    take_uid = uuid.uuid4()
    assert hunch_portfolio_identifier(take_uid) == f"HUNCH_PORTFOLIO__{take_uid.hex}"
    assert hunch_portfolio_identifier(str(take_uid)) == hunch_portfolio_identifier(take_uid)


@pytest.mark.skipif(
    not os.environ.get("HUNCH_LOCAL_RUNTIME_TESTS"),
    reason="needs the local MetaTables runtime (HUNCH_LOCAL_RUNTIME_TESTS=1)",
)
def test_basket_signal_identity_depends_only_on_the_take_on_the_local_runtime() -> None:
    from hunch.runtime import start_markets_engine
    from metatables import configure_local_client

    configure_local_client()
    start_markets_engine()
    take_uid = uuid.uuid4()
    a = basket_signal(take_uid, ["BBG000B9XRY4"])
    b = basket_signal(take_uid, ["BBG000B9XRY4", "BBG000BPH459", "BBG000N9MNX3"])
    assert a.signal_uid == b.signal_uid == basket_signal_uid(take_uid)
    assert basket_signal_uid(uuid.uuid4()) != a.signal_uid
    assert b.get_asset_list() == sorted(["BBG000B9XRY4", "BBG000BPH459", "BBG000N9MNX3"])


def test_sqlite_uuid_shim_coerces_strings_and_is_idempotent() -> None:
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.sql import sqltypes

    install_compat_patches()
    install_compat_patches()
    processor = sqltypes.Uuid().bind_processor(sqlite.dialect())
    value = uuid.uuid4()
    assert processor(str(value)) == processor(value)
    with pytest.raises(AttributeError):
        processor("not-a-uuid")  # not a UUID: the upstream processor still refuses it
