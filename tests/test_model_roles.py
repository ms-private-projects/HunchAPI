"""Model roles: each kind of recorded model call selects its own provider, model and credential."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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


@pytest.fixture
def shared_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ROLE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HUNCH_INFERENCE_PROVIDER", "openrouter")
    monkeypatch.setenv("HUNCH_INFERENCE_MODEL", "openai/gpt-5.4")
    monkeypatch.setenv("HUNCH_INFERENCE_CREDENTIAL", "openrouter")


def test_every_role_starts_from_the_shared_selection(shared_selection) -> None:
    assert set(model_roles()) == set(MODEL_ROLES) == {"research", "review", "analysis"}
    for role in MODEL_ROLES:
        selection = model_role(role)
        assert selection.role == role
        assert (selection.provider, selection.model) == ("openrouter", "openai/gpt-5.4")
        assert (selection.thinking, selection.credential) == ("medium", "openrouter")


def test_a_role_override_keeps_the_shared_values_it_does_not_name(
    shared_selection, monkeypatch
) -> None:
    monkeypatch.setenv("HUNCH_MODEL_ANALYSIS", "model=anthropic/claude-haiku-4.5 thinking=low")
    monkeypatch.setenv("HUNCH_MODEL_REVIEW", "provider=deemachine-ollama model=qwen3.8:27b")
    analysis = model_role("analysis")
    assert analysis.as_dict() == {
        "provider": "openrouter",
        "model": "anthropic/claude-haiku-4.5",
        "thinking": "low",
        "credential": "openrouter",
    }
    review = model_role("review")
    assert (review.provider, review.model) == ("deemachine-ollama", "qwen3.8:27b")
    assert model_role("research").model == "openai/gpt-5.4"


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
    monkeypatch.setenv("HUNCH_MODEL_ANALYSIS", "model=anthropic/claude-haiku-4.5 thinking=low")
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
    assert call["provider"] == "openrouter"
    assert call["model"] == "anthropic/claude-haiku-4.5"
    assert call["thinking_level"] == "low"
    assert call["custom_id"] == "openrouter"
    assert call["metadata"] == {
        "operation": "hunch-test",
        "model_role": "analysis",
        "take_uid": "t",
    }
    assert call["idempotency_key"].startswith("hunch-test-")
    assert completion.content == {"ok": True}
    assert (completion.provider, completion.model) == ("openrouter", "anthropic/claude-haiku-4.5")
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
    assert client.calls[0]["model"] == "openai/gpt-5.4"


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
