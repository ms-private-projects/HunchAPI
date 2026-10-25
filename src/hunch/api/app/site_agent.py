"""The Hunch Agent that the site's conversation opens, found when a request arrives.

The site mounts the Command Center conversation with an Agent and that Agent's Organization
Environment. Neither UID is part of the site's build: the API returns both in the project
configuration the site reads on page load (`GET /v1/project-state/configuration`), from one lookup
so the pair cannot drift apart.

The lookup selects the Agent that the source Agent Card names, in the Organization Environment and
on the CodeRepositoryBranch the SDK context resolves for this process, with a deployed runtime
release. Nothing comes from the request, the workflow file or the browser. The workflow gives the
API's workload `user` on the Agent (`access.resources`), which lets the hosted API see it.

A failure means "no Agent", never a failed configuration.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The Harness Agent is deployed from this card at the repository root. The image installs this
# package in editable mode from its checkout, so the card sits next to the source there too.
CARD_PATH = Path(__file__).resolve().parents[4] / ".agents" / "agent_card.json"
LOOKUP_OPERATION = "Hunch Agent lookup"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SiteAgent:
    """This branch's deployed Hunch Agent and the Organization Environment it belongs to."""

    agent_uid: str
    organization_environment_uid: str


def agent_card_name() -> str | None:
    """Return the Agent's name from its source card, or None when the card is missing or invalid."""
    try:
        card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
        name, description = card["name"], card["description"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(description, str) or not description.strip():
        return None
    return name


def _uid(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


def resolve_site_agent() -> SiteAgent | None:
    """Find this branch's deployed Hunch Agent, or return None when it cannot be named exactly."""
    name = agent_card_name()
    if name is None:
        logger.warning("The Hunch Agent Card is missing or invalid; no Agent is returned.")
        return None
    try:
        from mainsequence.client.agent_runtime_models import Agent
        from mainsequence.code_repository_context import (
            resolve_code_repository_branch_uid,
            resolve_organization_environment_uid,
        )

        environment_uid = _uid(resolve_organization_environment_uid(LOOKUP_OPERATION))
        branch_uid = _uid(resolve_code_repository_branch_uid(LOOKUP_OPERATION))
        if environment_uid is None or branch_uid is None:
            return None
        matches = [
            agent
            for agent in Agent.filter(name=name)
            if agent.name == name
            and _uid(agent.organization_environment_uid) == environment_uid
            and _uid(agent.code_repository_branch_uid) == branch_uid
        ]
        if len(matches) != 1:
            return None
        agent_uid = _uid(matches[0].uid)
        if agent_uid is None or not matches[0].runtime_release_uid:
            return None
        return SiteAgent(agent_uid=agent_uid, organization_environment_uid=environment_uid)
    except Exception as exc:
        # The exception's text can carry dependency internals; name only its type.
        logger.warning(
            "The Hunch Agent lookup failed (%s); no Agent is returned.", type(exc).__name__
        )
        return None


__all__ = ["CARD_PATH", "SiteAgent", "agent_card_name", "resolve_site_agent"]
