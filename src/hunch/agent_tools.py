"""Structured project tools the Hunch Agent uses through the API's MCP server.

`hunch.api.app.mcp_server` serves this catalog at the API's `/mcp` endpoint, so every call runs
inside the API's verified request identity: the caller, and on the Agent's call the person it works
for. The handlers reuse the same application services as the REST routes and contain no second copy
of the business logic. The Agent never reaches a connector: Hunch services do, deterministically.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from hunch.settings import EXECUTION_MODES, RESEARCH_MODES, TAKE_STATUSES
from hunch.takes.services import TakeCreate, TakeUpdate

ToolHandler = Callable[[Mapping[str, Any]], Any]
ExecutionMode = Literal["parallel", "sequential"]

# A build researches with a recorded model call; give it well over the 60-second MCP default.
BUILD_TOOL_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class ProjectAgentTool:
    """One Tau-visible tool backed by a synchronous project service."""

    name: str
    label: str
    description: str
    parameters: dict[str, Any]
    execution_mode: ExecutionMode
    handler: ToolHandler
    timeout_seconds: int | None = None


# Schema helpers ----------------------------------------------------------------------------------


def _inline_model_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a self-contained JSON schema suitable for nesting in a tool case."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def resolve(value: Any) -> Any:
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            key = reference.removeprefix("#/$defs/")
            if key not in definitions:
                raise ValueError(f"Unresolved Pydantic schema reference: {reference}")
            replacement = resolve(copy.deepcopy(definitions[key]))
            siblings = {key: item for key, item in value.items() if key != "$ref"}
            if siblings:
                replacement = {**replacement, **resolve(siblings)}
            return replacement
        return {key: resolve(item) for key, item in value.items()}

    return resolve(schema)


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


def _enum(values: tuple[str, ...], description: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values), "description": description}


def _request(model: type[BaseModel], description: str) -> dict[str, Any]:
    schema = _inline_model_schema(model)
    schema["description"] = description
    return schema


def _page_properties(*, maximum: int = 100) -> dict[str, dict[str, Any]]:
    return {
        "limit": {"type": "integer", "minimum": 1, "maximum": maximum, "default": 25},
        "offset": {"type": "integer", "minimum": 0, "default": 0},
    }


# Argument helpers --------------------------------------------------------------------------------


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


def _optional_text(arguments: Mapping[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string when supplied.")
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


def _request_model(arguments: Mapping[str, Any], model: type[BaseModel]) -> BaseModel:
    raw = arguments.get("request")
    if not isinstance(raw, Mapping):
        raise ValueError("request must be an object.")
    return model.model_validate(dict(raw))


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


def profile(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services.profile import get_profile, patch_profile

    operation = _operation(arguments, {"get", "update"})
    user = acting_user()
    if operation == "get":
        return get_profile(user)
    return patch_profile(
        user,
        handle=_optional_text(arguments, "handle"),
        display_name=_optional_text(arguments, "display_name"),
    )


def query_takes(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services.takes import get_take_resource, list_take_resources

    operation = _operation(arguments, {"list", "get"})
    user = acting_user()
    if operation == "get":
        take_uid = _required_text(arguments, "take_uid")
        return _require_found(get_take_resource(user, take_uid), label="Take", uid=take_uid)
    limit, offset = _page(arguments)
    scope = _optional_text(arguments, "scope") or "mine"
    if scope not in {"mine", "public"}:
        raise ValueError("scope must be mine or public.")
    return list_take_resources(
        user,
        scope=scope,  # type: ignore[arg-type]
        status=_optional_text(arguments, "status"),
        search=_optional_text(arguments, "search"),
        limit=limit,
        offset=offset,
    )


def manage_take(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import takes as service

    operation = _operation(
        arguments,
        {"create", "update", "set_execution_mode", "publish", "unpublish", "fork", "archive"},
    )
    user = acting_user()
    if operation == "create":
        return service.create_take_resource(user, _request_model(arguments, TakeCreate))
    take_uid = _required_text(arguments, "take_uid")
    if operation == "update":
        return service.update_take_resource(user, take_uid, _request_model(arguments, TakeUpdate))
    if operation == "set_execution_mode":
        return service.set_execution_mode_resource(
            user, take_uid, _required_text(arguments, "execution_mode")
        )
    if operation == "publish":
        return service.publish_take_resource(user, take_uid)
    if operation == "unpublish":
        return service.unpublish_take_resource(user, take_uid)
    if operation == "fork":
        return service.fork_take_resource(user, take_uid)
    return service.archive_take_resource(user, take_uid, _required_text(arguments, "confirmation"))


def build_take(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import portfolios as service

    operation = _operation(arguments, {"build", "activate_practice", "refresh"})
    user = acting_user()
    take_uid = _required_text(arguments, "take_uid")
    if operation == "build":
        return service.build_take_resource(
            user, take_uid, research_mode=_optional_text(arguments, "research_mode")
        )
    if operation == "activate_practice":
        return service.activate_practice_resource(user, take_uid)
    return service.refresh_take_resource(user, take_uid)


def query_portfolio(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import portfolios as service

    operation = _operation(arguments, {"revisions", "performance", "weights"})
    user = acting_user()
    take_uid = _required_text(arguments, "take_uid")
    if operation == "revisions":
        return service.take_revision_resources(user, take_uid)
    if operation == "performance":
        return service.take_performance_frame(user, take_uid)
    return service.take_weights_resource(user, take_uid)


def query_instruments(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services.instruments import (
        get_instrument_resource,
        list_instrument_resources,
    )

    operation = _operation(arguments, {"list", "get"})
    acting_user()
    if operation == "get":
        identifier = _required_text(arguments, "identifier")
        return _require_found(
            get_instrument_resource(identifier), label="Instrument", uid=identifier
        )
    limit, offset = _page(arguments)
    return list_instrument_resources(
        search=_optional_text(arguments, "search"),
        sector=_optional_text(arguments, "sector"),
        limit=limit,
        offset=offset,
    )


def get_job_run_status(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.operations.builds import job_run_status

    acting_user()
    job_run_uid = _required_text(arguments, "job_run_uid")
    return _require_found(job_run_status(job_run_uid), label="JobRun", uid=job_run_uid)


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
        name="hunch_profile",
        label="My Hunch Profile",
        description=(
            "Read or update the profile of the person you serve: their public handle and display "
            "name. The profile is created on first contact."
        ),
        parameters=_operations(
            _operation_case("get"),
            _operation_case(
                "update",
                properties={
                    "handle": _string("New public handle: 3 to 32 lower-case letters, digits, _."),
                    "display_name": _string("New display name."),
                },
            ),
        ),
        execution_mode="sequential",
        handler=profile,
    ),
    ProjectAgentTool(
        name="hunch_query_takes",
        label="Query Takes",
        description=(
            "List the takes of the person you serve (scope mine) or everyone's published takes "
            "(scope public), or read one take they own or that is public."
        ),
        parameters=_operations(
            _operation_case(
                "list",
                properties={
                    **PAGE,
                    "scope": _enum(("mine", "public"), "mine (default) or public."),
                    "status": _enum(TAKE_STATUSES, "Only takes in this status."),
                    "search": _string("Case-insensitive text in the title or thesis."),
                },
            ),
            _operation_case("get", properties={"take_uid": _uid("take")}, required=("take_uid",)),
        ),
        execution_mode="parallel",
        handler=query_takes,
    ),
    ProjectAgentTool(
        name="hunch_manage_take",
        label="Manage A Take",
        description=(
            "Create a take, edit its title, thesis or constraints, set its execution mode, publish "
            "or unpublish it, fork a published take, or archive one. Archiving needs the exact "
            "confirmation `DELETE <take uid>` typed by the person."
        ),
        parameters=_operations(
            _operation_case(
                "create",
                properties={"request": _request(TakeCreate, "The new take.")},
                required=("request",),
            ),
            _operation_case(
                "update",
                properties={
                    "take_uid": _uid("take"),
                    "request": _request(TakeUpdate, "Fields to change."),
                },
                required=("take_uid", "request"),
            ),
            _operation_case(
                "set_execution_mode",
                properties={
                    "take_uid": _uid("take"),
                    "execution_mode": _enum(EXECUTION_MODES, "practice, approval or autopilot."),
                },
                required=("take_uid", "execution_mode"),
            ),
            _operation_case(
                "publish", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
            _operation_case(
                "unpublish", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
            _operation_case("fork", properties={"take_uid": _uid("take")}, required=("take_uid",)),
            _operation_case(
                "archive",
                properties={
                    "take_uid": _uid("take"),
                    "confirmation": _string("Exactly: DELETE <take uid>."),
                },
                required=("take_uid", "confirmation"),
            ),
        ),
        execution_mode="sequential",
        handler=manage_take,
    ),
    ProjectAgentTool(
        name="hunch_build_take",
        label="Build A Take",
        description=(
            "Build (or rebuild) the basket of an owned take: research the thesis, apply its "
            "constraints, publish the weights and compute the portfolio; then activate it as a "
            "practice take or refresh its values. Hosted builds return a JobRun UID to follow."
        ),
        parameters=_operations(
            _operation_case(
                "build",
                properties={
                    "take_uid": _uid("take"),
                    "research_mode": _enum(
                        RESEARCH_MODES, "Override the configured research mode."
                    ),
                },
                required=("take_uid",),
            ),
            _operation_case(
                "activate_practice", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
            _operation_case(
                "refresh", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
        ),
        execution_mode="sequential",
        handler=build_take,
        timeout_seconds=BUILD_TOOL_TIMEOUT_SECONDS,
    ),
    ProjectAgentTool(
        name="hunch_query_portfolio",
        label="Query A Take's Portfolio",
        description=(
            "Read what Hunch built for a take: its basket revisions with rationale and guardrail "
            "notes, its latest weights, or its performance since activation."
        ),
        parameters=_operations(
            _operation_case(
                "revisions", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
            _operation_case(
                "weights", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
            _operation_case(
                "performance", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
        ),
        execution_mode="parallel",
        handler=query_portfolio,
    ),
    ProjectAgentTool(
        name="hunch_query_instruments",
        label="Query Instruments",
        description="List or search the instruments Hunch can hold, or read one by ticker or FIGI.",
        parameters=_operations(
            _operation_case(
                "list",
                properties={
                    **PAGE,
                    "search": _string("Ticker, name or theme text."),
                    "sector": _string("Exact sector label."),
                },
            ),
            _operation_case(
                "get",
                properties={"identifier": _string("Ticker or FIGI.")},
                required=("identifier",),
            ),
        ),
        execution_mode="parallel",
        handler=query_instruments,
    ),
    ProjectAgentTool(
        name="hunch_get_job_run_status",
        label="Get Hunch JobRun Status",
        description="Read one Hunch build or refresh JobRun status and its sanitized failure summary.",
        parameters={
            "type": "object",
            "properties": {"job_run_uid": _uid("JobRun")},
            "required": ["job_run_uid"],
            "additionalProperties": False,
        },
        execution_mode="parallel",
        handler=get_job_run_status,
    ),
)


__all__ = [
    "BUILD_TOOL_TIMEOUT_SECONDS",
    "PROJECT_AGENT_TOOLS",
    "ProjectAgentTool",
    "build_take",
    "get_job_run_status",
    "manage_take",
    "profile",
    "project_state",
    "query_instruments",
    "query_portfolio",
    "query_takes",
]
