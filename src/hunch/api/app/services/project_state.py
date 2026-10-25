"""Project state: capability catalog and runtime configuration."""

from __future__ import annotations

from hunch import __version__
from hunch.api.app.schemas import ProjectConfigurationResponse
from hunch.api.app.site_agent import resolve_site_agent
from hunch.settings import VENUES


def get_project_configuration(
    *, request_user_uid: str | None = None
) -> ProjectConfigurationResponse:
    """The configuration the site and the Agent read first.

    The Agent lookup is best effort and never fails the response.
    """
    agent = resolve_site_agent()
    return ProjectConfigurationResponse(
        api_version=__version__,
        venues=list(VENUES),
        organization_environment_uid=agent.organization_environment_uid if agent else None,
        agent_uid=agent.agent_uid if agent else None,
        request_user_uid=request_user_uid,
    )


__all__ = ["get_project_configuration"]
