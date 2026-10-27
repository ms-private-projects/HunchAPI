"""The take's weight signal: one ms-markets signal per take with a history of baskets.

ms-markets derives a signal's identity from the signal class path and its configuration. The
configuration here is only the take UID, so the identity is stable while the basket changes: each
build publishes a new observation of weights (dropped names at 0) and the portfolio graph
rebalances to the latest one. The module path of `HunchBasketSignal` is part of every take's
signal UID: never move or rename the class.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence

import pandas as pd

from msm_portfolios.configuration import PortfolioConfigBaseModel
from msm_portfolios.time_index import ASSET_IDENTIFIER, SignalWeights


class HunchBasketSignalConfig(PortfolioConfigBaseModel):
    """Stable configuration: the take the signal belongs to."""

    basket_id: str


class HunchBasketSignal(SignalWeights):
    """Weights Hunch publishes for one take; observations are set, never calculated here."""

    _universe: list[str] = []

    def maximum_forward_fill(self) -> dt.timedelta:
        return dt.timedelta(days=36500)

    def get_asset_list(self) -> list[str]:
        return list(self._universe)

    def dependencies(self) -> dict:
        return {}


def basket_signal(take_uid: uuid.UUID | str, universe: Sequence[str]) -> HunchBasketSignal:
    """The take's signal node, aware of every instrument the take ever held."""
    from hunch.series import portfolio_series

    signal = HunchBasketSignal.from_signal_configuration(
        HunchBasketSignalConfig(basket_id=str(uuid.UUID(str(take_uid)))),
        output_table=portfolio_series()["signal_weights"],
    )
    signal._universe = sorted(dict.fromkeys(universe))
    return signal


def basket_signal_uid(take_uid: uuid.UUID | str) -> str:
    return basket_signal(take_uid, []).signal_uid


def publish_basket_observation(
    signal: HunchBasketSignal,
    weights_by_figi: Mapping[str, float],
    time_index: dt.datetime,
    *,
    description: str | None = None,
) -> None:
    """Publish one observation: every universe instrument, dropped names at 0."""
    universe = signal.get_asset_list()
    unknown = sorted(set(weights_by_figi) - set(universe))
    if unknown:
        raise ValueError(f"Weights name instruments outside the signal universe: {unknown}")
    stamp = (
        pd.Timestamp(time_index).tz_convert("UTC")
        if pd.Timestamp(time_index).tzinfo
        else pd.Timestamp(time_index, tz="UTC")
    )
    frame = pd.DataFrame(
        {"signal_weight": [float(weights_by_figi.get(figi, 0.0)) for figi in universe]},
        index=pd.MultiIndex.from_arrays(
            [[stamp] * len(universe), universe], names=["time_index", ASSET_IDENTIFIER]
        ),
    )
    error, _ = signal.set_signal_weights_frame(frame, signal_description=description).run(
        update_tree=False
    )
    if error:
        raise RuntimeError("Publishing the basket weights failed.")


__all__ = [
    "HunchBasketSignal",
    "HunchBasketSignalConfig",
    "basket_signal",
    "basket_signal_uid",
    "publish_basket_observation",
]
