"""Structured project tools the Hunch Agent uses through the API's MCP server.

`hunch.api.app.mcp_server` serves this catalog at the API's `/mcp` endpoint, so every call runs
inside the API's verified request identity: the caller, and on the Agent's call the person it works
for. The handlers reuse the same application services as the REST routes and contain no second copy
of the business logic. The Agent never reaches a connector: Hunch services do, deterministically.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

ToolHandler = Callable[[Mapping[str, Any]], Any]
ExecutionMode = Literal["parallel", "sequential"]


@dataclass(frozen=True, slots=True)
class ProjectAgentTool:
    """One Tau-visible tool backed by a synchronous project service."""

    name: str
    label: str
    description: str
    parameters: dict[str, Any]
    execution_mode: ExecutionMode
    handler: ToolHandler


def _operation_case(
    operation: str,
    *,
    properties: Mapping[str, Mapping[str, Any]] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "const": operation},
            **dict(properties or {}),
        },
        "required": ["operation", *required],
        "additionalProperties": False,
    }


def _operations(*cases: dict[str, Any]) -> dict[str, Any]:
    # MCP requires an object input schema at the root, even for discriminated operations.
    return {"type": "object", "oneOf": list(cases)}


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "description": description}


def _uid(label: str) -> dict[str, Any]:
    return _string(f"Public UID of the {label}.")


def _page_properties(*, maximum: int = 100) -> dict[str, dict[str, Any]]:
    return {
        "limit": {"type": "integer", "minimum": 1, "maximum": maximum, "default": 25},
        "offset": {"type": "integer", "minimum": 0, "default": 0},
    }


def _operation(arguments: Mapping[str, Any], allowed: set[str]) -> str:
    operation = str(arguments.get("operation") or "").strip()
    if operation not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"operation must be one of: {choices}.")
    return operation


def _required_text(arguments: Mapping[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string.")
    return value.strip()


def _integer(
    arguments: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = arguments.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be an integer between {minimum} and {maximum}.")
    return value


def _page(arguments: Mapping[str, Any], *, maximum: int = 100) -> tuple[int, int]:
    limit = _integer(arguments, "limit", default=25, minimum=1, maximum=maximum)
    offset = _integer(arguments, "offset", default=0, minimum=0, maximum=2_147_483_647)
    if offset % limit:
        raise ValueError("offset must be an exact multiple of limit.")
    return limit, offset


def _require_found(value: Any, *, label: str, uid: str) -> Any:
    if value is None:
        raise LookupError(f"{label} {uid} does not exist.")
    return value


# Handlers ---------------------------------------------------------------------------------------


def project_state(_: Mapping[str, Any]) -> dict[str, Any]:
    from hunch.api.app.capabilities import capability_summaries
    from hunch.api.app.identity import bound_acting_user_uid
    from hunch.api.app.services.project_state import get_project_configuration

    configuration = get_project_configuration(request_user_uid=bound_acting_user_uid())
    return {"configuration": configuration, "capabilities": capability_summaries()}


def query_takes(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user_uid
    from hunch.api.app.services.takes import get_take_for_user, list_takes_for_user

    operation = _operation(arguments, {"list", "get"})
    user_uid = acting_user_uid()
    if operation == "get":
        take_uid = _required_text(arguments, "take_uid")
        return _require_found(get_take_for_user(take_uid, user_uid), label="Take", uid=take_uid)
    limit, offset = _page(arguments)
    return list_takes_for_user(user_uid, limit=limit, offset=offset)


# Catalog ----------------------------------------------------------------------------------------

PAGE = _page_properties()

PROJECT_AGENT_TOOLS: tuple[ProjectAgentTool, ...] = (
    ProjectAgentTool(
        name="hunch_project_state",
        label="Inspect Hunch Project State",
        description=(
            "Read the implemented Hunch capability catalog, the venues, the deployed Agent and "
            "the disclaimers for this CodeRepositoryBranch."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution_mode="parallel",
        handler=project_state,
    ),
    ProjectAgentTool(
        name="hunch_query_takes",
        label="Query Takes",
        description=(
            "List the takes of the person you serve, or read one take they own or that is public."
        ),
        parameters=_operations(
            _operation_case("list", properties={**PAGE}),
            _operation_case("get", properties={"take_uid": _uid("take")}, required=("take_uid",)),
        ),
        execution_mode="parallel",
        handler=query_takes,
    ),
)


__all__ = [
    "PROJECT_AGENT_TOOLS",
    "ProjectAgentTool",
    "project_state",
    "query_takes",
]
