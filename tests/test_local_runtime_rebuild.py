"""A second build in the same session reaches the portfolio, against the local MetaTables runtime.

Skipped unless `HUNCH_LOCAL_RUNTIME_TESTS=1`; needs the local MetaTables API up and migrated, the
loopback Markets API (`MARKETS_API_URL`, from `scripts/dev_stack.sh`) and an SDK sign-in. It writes
real rows into the local database (a take, its research, two revisions and its portfolio). Without
`MARKETS_API_URL` the SDK discovers the Environment's hosted Markets API and the take's signal
metadata would land there, so the test refuses to run.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("HUNCH_LOCAL_RUNTIME_TESTS"),
    reason="needs the local MetaTables runtime (HUNCH_LOCAL_RUNTIME_TESTS=1)",
)

USER = f"runtime-test-{uuid.uuid4().hex[:8]}"


def test_a_second_build_in_the_same_session_reaches_the_portfolio(monkeypatch) -> None:
    if not os.environ.get("MARKETS_API_URL", "").startswith("http://127.0.0.1:"):
        pytest.fail(
            "MARKETS_API_URL must point at the loopback Markets API (scripts/dev_stack.sh)."
        )
    monkeypatch.setenv("HUNCH_RESEARCH_MODE", "heuristic")
    from metatables import configure_local_client

    configure_local_client()
    from hunch.portfolios.build import build_take
    from hunch.portfolios.graph import portfolio_latest_weights
    from hunch.portfolios.services import hunch_portfolio_identifier
    from hunch.research.runs import run_take_research
    from hunch.runtime import start_markets_engine
    from hunch.takes import Take
    from hunch.takes.services import TakeConstraints, TakeCreate, create_take

    start_markets_engine()
    take = create_take(
        USER,
        TakeCreate(
            title="Runtime test: same-session rebuild",
            thesis_text="Humanoid robots in every home; chips and actuators are the chokepoints.",
        ),
        username="runtime@example.test",
    )
    run_take_research(take.uid, mode="heuristic", created_by="test")
    identifier = hunch_portfolio_identifier(take.uid)

    def stored() -> dict[str, float]:
        return {
            str(row["asset_identifier"]): round(float(row["weight"]), 6)
            for row in portfolio_latest_weights(identifier)
            if float(row["weight"]) > 0
        }

    first = build_take(take.uid, created_by="test")
    assert stored() == {w.figi: round(w.weight, 6) for w in first.proposal.weights}

    # Another basket from the same research, built before the next close.
    dropped = [w.ticker for w in first.proposal.weights[:2]]
    Take.update(
        take.uid,
        constraints_json=TakeConstraints(exclusions=dropped, max_positions=4).model_dump(),
        updated_at=dt.datetime.now(dt.timezone.utc),
    )
    second = build_take(take.uid, created_by="test")
    assert second.revision.signal_time_index == first.revision.signal_time_index
    assert second.proposal.weights_by_figi() != first.proposal.weights_by_figi()
    assert stored() == {w.figi: round(w.weight, 6) for w in second.proposal.weights}
