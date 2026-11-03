"""Model roles: each kind of recorded model call selects its own provider, model and credential."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from hunch.research.inference import recorded_completion
from hunch.research.models import ResearchError
from hunch.settings import MODEL_ROLES, model_role, model_roles

ROLE_VARIABLES = (
    "HUNCH_INFERENCE_PROVIDER",
    "HUNCH_INFERENCE_MODEL",
    "HUNCH_INFERENCE_THINKING",
    "HUNCH_INFERENCE_CREDENTIAL",
    "HUNCH_MODEL_RESEARCH",
    "HUNCH_MODEL_REVIEW",
    "HUNCH_MODEL_ANALYSIS",
)
WORKFLOW = Path(__file__).resolve().parents[1] / ".mainsequence/workflows/hunch-api.yaml"


@pytest.fixture
def shared_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ROLE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HUNCH_INFERENCE_PROVIDER", "meta")
    monkeypatch.setenv("HUNCH_INFERENCE_MODEL", "muse-spark-1.3")
    monkeypatch.setenv("HUNCH_INFERENCE_CREDENTIAL", "meta")


def test_every_role_starts_from_the_shared_selection(shared_selection) -> None:
    assert set(model_roles()) == set(MODEL_ROLES) == {"research", "review", "analysis"}
    for role in MODEL_ROLES:
        selection = model_role(role)
        assert selection.role == role
        assert (selection.provider, selection.model) == ("meta", "muse-spark-1.3")
        assert (selection.thinking, selection.credential) == ("medium", "meta")


def test_a_role_override_keeps_the_shared_values_it_does_not_name(
    shared_selection, monkeypatch
) -> None:
    monkeypatch.setenv("HUNCH_MODEL_RESEARCH", "model=muse-wonder-1.0")
    monkeypatch.setenv("HUNCH_MODEL_ANALYSIS", "thinking=low")
    monkeypatch.setenv("HUNCH_MODEL_REVIEW", "provider=deemachine-ollama model=qwen3.8:27b")
    research = model_role("research")
    assert research.as_dict() == {
        "provider": "meta",
        "model": "muse-wonder-1.0",
        "thinking": "medium",
        "credential": "meta",
    }
    analysis = model_role("analysis")
    assert (analysis.model, analysis.thinking) == ("muse-spark-1.3", "low")
    review = model_role("review")
    assert (review.provider, review.model) == ("deemachine-ollama", "qwen3.8:27b")


@pytest.mark.parametrize(
    "override", ["gpt-5", "size=big", "thinking=ultra", "model=", "provider=openai model"]
)
def test_malformed_overrides_are_refused(shared_selection, monkeypatch, override) -> None:
    monkeypatch.setenv("HUNCH_MODEL_ANALYSIS", override)
    with pytest.raises(ValueError):
        model_role("analysis")


def test_unknown_roles_are_refused(shared_selection) -> None:
    with pytest.raises(ValueError):
        model_role("chat")


class FakeInference:
    def __init__(self, content: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.content = content if content is not None else {"ok": True}

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            status="completed",
            content_available=True,
            output={"content": self.content},
            request_uid="req-1",
            conversation_uid="conv-1",
            provider=kwargs["provider"],
            model=kwargs["model"],
        )


def test_recorded_completion_runs_on_the_roles_model(shared_selection, monkeypatch) -> None:
    monkeypatch.setenv("HUNCH_MODEL_ANALYSIS", "model=muse-spark-1.2 thinking=low")
    client = FakeInference()
    completion = recorded_completion(
        system="s",
        user="u",
        schema={"type": "object"},
        operation="hunch-test",
        metadata={"take_uid": "t"},
        idempotency_prefix="hunch-test",
        client=client,
        role="analysis",
    )
    (call,) = client.calls
    assert call["provider"] == "meta"
    assert call["model"] == "muse-spark-1.2"
    assert call["thinking_level"] == "low"
    assert call["custom_id"] == "meta"
    assert call["metadata"] == {
        "operation": "hunch-test",
        "model_role": "analysis",
        "take_uid": "t",
    }
    assert call["idempotency_key"].startswith("hunch-test-")
    assert completion.content == {"ok": True}
    assert (completion.provider, completion.model) == ("meta", "muse-spark-1.2")
    assert (completion.request_uid, completion.conversation_uid) == ("req-1", "conv-1")


def test_recorded_completion_defaults_to_the_research_role(shared_selection) -> None:
    client = FakeInference()
    recorded_completion(
        system="s",
        user="u",
        schema={"type": "object"},
        operation="hunch-test",
        metadata={},
        idempotency_prefix="hunch-test",
        client=client,
    )
    assert client.calls[0]["metadata"]["model_role"] == "research"
    assert client.calls[0]["model"] == "muse-spark-1.3"


def test_a_misconfigured_role_fails_before_any_model_call(shared_selection, monkeypatch) -> None:
    monkeypatch.setenv("HUNCH_MODEL_ANALYSIS", "thinking=ultra")
    client = FakeInference()
    with pytest.raises(ResearchError, match="misconfigured"):
        recorded_completion(
            system="s",
            user="u",
            schema={"type": "object"},
            operation="hunch-test",
            metadata={},
            idempotency_prefix="hunch-test",
            client=client,
            role="analysis",
        )
    assert client.calls == []


def test_every_deployed_model_call_runs_on_muse(monkeypatch) -> None:
    """What the platform deploys: the Agent and every role of every workload that calls a model
    run a Muse model on the `meta` provider, and only the Meta credential is shared."""
    resources = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["resources"]
    (agent,) = [item for item in resources if item["kind"] == "harness_agent"]
    assert (agent["spec"]["llm_provider"], agent["spec"]["llm_model"]) == ("meta", "muse-spark-1.3")
    calling = {
        item["key"]: item for item in resources if item.get("access", {}).get("model_providers")
    }
    assert set(calling) == {"hunch", "hunch-take-research", "hunch-daily-review"}
    research = {}
    for key, item in calling.items():
        assert {share["provider"] for share in item["access"]["model_providers"]} == {"meta"}
        for name in ROLE_VARIABLES:
            monkeypatch.delenv(name, raising=False)
        for variable in item["spec"]["env_vars"]:
            if variable["name"] in ROLE_VARIABLES:
                monkeypatch.setenv(variable["name"], variable["value"])
        for role, selection in model_roles().items():
            assert selection.provider == "meta", (key, role)
            assert selection.model in {"muse-spark-1.3", "muse-wonder-1.0"}, (key, role)
            assert selection.credential == "meta", (key, role)
        research[key] = model_role("research").model
    # Research runs in its Job on Muse Wonder 1.0; the API reports the same selection.
    assert research["hunch-take-research"] == research["hunch"] == "muse-wonder-1.0"
