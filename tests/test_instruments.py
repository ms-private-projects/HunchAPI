"""Seeding the universe writes the Markets registries before Hunch's instrument rows."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hunch.instruments import services


@pytest.fixture
def markets(monkeypatch):
    calls: list[str] = []
    fixture = services.universe_fixture()[:2]
    monkeypatch.setattr(services, "universe_fixture", lambda: fixture)
    monkeypatch.setattr(services, "AssetType", SimpleNamespace(upsert=lambda **_: None))
    monkeypatch.setattr(services, "ensure_cash_asset", lambda: None)
    monkeypatch.setattr(
        services,
        "ensure_asset",
        lambda figi, _type: calls.append(f"asset {figi}") or SimpleNamespace(uid=f"uid-{figi}"),
    )
    monkeypatch.setattr(
        services,
        "OpenFigiDetails",
        SimpleNamespace(upsert=lambda **row: calls.append(f"details {row['figi']}")),
    )
    monkeypatch.setattr(
        services,
        "AssetCategory",
        SimpleNamespace(
            upsert=lambda **_: SimpleNamespace(uid="category"),
            replace_memberships=lambda **kw: calls.append(f"category {len(kw['asset_uids'])}"),
        ),
    )
    monkeypatch.setattr(
        "msm.api.assets.AssetSnapshots",
        SimpleNamespace(publish=lambda rows: calls.append(f"snapshots {len(rows)}")),
    )
    monkeypatch.setattr(
        services,
        "HunchInstrument",
        SimpleNamespace(upsert=lambda **row: calls.append(f"instrument {row['figi']}")),
    )
    monkeypatch.setattr(services, "list_instruments", lambda: [])
    return calls, fixture


def test_instrument_rows_are_written_after_the_markets_registries(markets) -> None:
    calls, fixture = markets
    services.seed_universe()
    first, second = (row["figi"] for row in fixture)
    assert calls == [
        f"asset {first}",
        f"details {first}",
        f"asset {second}",
        f"details {second}",
        "snapshots 2",
        "category 2",
        f"instrument {first}",
        f"instrument {second}",
    ]


def test_a_failed_publish_leaves_the_universe_unseeded(markets, monkeypatch) -> None:
    calls, _ = markets

    def fail(rows):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr("msm.api.assets.AssetSnapshots", SimpleNamespace(publish=fail))
    with pytest.raises(TimeoutError):
        services.seed_universe()
    assert not [call for call in calls if call.startswith("instrument")]
