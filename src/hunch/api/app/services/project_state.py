"""Project state: capability catalog and runtime configuration."""

from __future__ import annotations

import os
import time
from urllib.parse import urlsplit

import requests

from hunch import __version__
from hunch.api.app.schemas import (
    AssistantConfiguration,
    AssistantRuntime,
    ConnectorConfiguration,
    ModelRoleConfiguration,
    ProjectConfigurationResponse,
    ResearchConfiguration,
)
from hunch.api.app.site_agent import SiteAgent, resolve_site_agent
from hunch.connectors import connector_status
from hunch.settings import (
    VENUES,
    bars_provider,
    build_execution,
    connector_mode,
    inference_model,
    inference_provider,
    model_roles,
    research_mode,
)

LOCAL_TAU_ORIGIN_ENV = "HUNCH_LOCAL_TAU_ORIGIN"
LOCAL_TAU_BASE_PATH = "/tau"
LOCAL_TAU_PROBE_CACHE_SECONDS = 20.0
AGENT_DISPLAY_NAME = "Hunch Agent"

_local_tau_probe: tuple[float, bool] | None = None


def _local_tau_origin() -> str | None:
    """The loopback Tau origin the local launcher names, validated; None when not configured."""
    origin = os.environ.get(LOCAL_TAU_ORIGIN_ENV, "").strip()
    if not origin:
        return None
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port is None
        or parsed.path not in {"", "/"}
    ):
        return None
    return origin.rstrip("/")


def local_tau_ready(*, now: float | None = None) -> bool:
    """Whether a local Tau runtime answers `/ready` in local mode (probe cached briefly)."""
    global _local_tau_probe
    origin = _local_tau_origin()
    if origin is None:
        return False
    current = time.monotonic() if now is None else now
    if (
        _local_tau_probe is not None
        and current - _local_tau_probe[0] < LOCAL_TAU_PROBE_CACHE_SECONDS
    ):
        return _local_tau_probe[1]
    ready = False
    try:
        response = requests.get(f"{origin}/ready", timeout=2.0)
        body = response.json() if response.status_code == 200 else {}
        ready = bool(body.get("ok")) and body.get("mode") == "local"
    except (requests.RequestException, ValueError):
        ready = False
    _local_tau_probe = (current, ready)
    return ready


def assistant_configuration(agent: SiteAgent | None) -> AssistantConfiguration:
    if agent is not None:
        return AssistantConfiguration(
            enabled=True,
            runtime=AssistantRuntime(mode="platform"),
            agent_uid=agent.agent_uid,
            environment_uid=agent.organization_environment_uid,
            display_name=AGENT_DISPLAY_NAME,
        )
    if local_tau_ready():
        return AssistantConfiguration(
            enabled=True,
            runtime=AssistantRuntime(mode="local", base_path=LOCAL_TAU_BASE_PATH),
            display_name=AGENT_DISPLAY_NAME,
        )
    return AssistantConfiguration(enabled=False, display_name=AGENT_DISPLAY_NAME)


def research_configuration() -> ResearchConfiguration:
    mode = research_mode()
    return ResearchConfiguration(
        mode=mode,
        build_execution=build_execution(),
        bars_provider=bars_provider(),
        inference_provider=inference_provider() if mode == "inference" else None,
        inference_model=inference_model() if mode == "inference" else None,
        models={
            role: ModelRoleConfiguration(**selection.as_dict())
            for role, selection in model_roles().items()
        },
    )


def connector_configuration() -> ConnectorConfiguration:
    return ConnectorConfiguration(
        mode=connector_mode(),
        venues={venue: bool(connector_status(venue)["configured"]) for venue in VENUES},
    )


def get_project_configuration(
    *, request_user_uid: str | None = None
) -> ProjectConfigurationResponse:
    """The configuration the site and the Agent read first.

    The Agent lookup and the local Tau probe are best effort and never fail the response.
    """
    agent = resolve_site_agent()
    return ProjectConfigurationResponse(
        api_version=__version__,
        venues=list(VENUES),
        research=research_configuration(),
        connectors=connector_configuration(),
        assistant=assistant_configuration(agent),
        organization_environment_uid=agent.organization_environment_uid if agent else None,
        agent_uid=agent.agent_uid if agent else None,
        request_user_uid=request_user_uid,
    )


__all__ = [
    "assistant_configuration",
    "connector_configuration",
    "get_project_configuration",
    "local_tau_ready",
    "research_configuration",
]
