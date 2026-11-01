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

from hunch.api.app.schemas import FundRequest, LinkAccountRequest
from hunch.settings import (
    EXECUTION_MODES,
    PROPOSAL_STATUSES,
    RESEARCH_MODES,
    TAKE_STATUSES,
    VENUES,
)
from hunch.takes.services import TakeCreate, TakeUpdate

ToolHandler = Callable[[Mapping[str, Any]], Any]
ExecutionMode = Literal["parallel", "sequential"]

# A research is one recorded model call and a build runs the portfolio graph; give both well over
# the 60-second MCP default.
BUILD_TOOL_TIMEOUT_SECONDS = 300
# An analysis is one recorded completion with a 90-second platform deadline.
ANALYSIS_TOOL_TIMEOUT_SECONDS = 120


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
    digest = arguments.get("email_digest")
    if digest is not None and not isinstance(digest, bool):
        raise ValueError("email_digest must be true or false.")
    return patch_profile(
        user,
        handle=_optional_text(arguments, "handle"),
        display_name=_optional_text(arguments, "display_name"),
        email_digest=digest,
        email_address=_optional_text(arguments, "email_address"),
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


def research_take(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import research as service

    operation = _operation(arguments, {"run", "list", "get"})
    user = acting_user()
    take_uid = _required_text(arguments, "take_uid")
    if operation == "run":
        return service.research_take_resource(
            user, take_uid, research_mode=_optional_text(arguments, "research_mode")
        )
    if operation == "get":
        return service.get_take_research_resource(
            user, take_uid, _required_text(arguments, "research_uid")
        )
    limit = _integer(arguments, "limit", default=10, minimum=1, maximum=100)
    return service.take_research_resources(user, take_uid, limit=limit)


def build_take(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import portfolios as service

    operation = _operation(arguments, {"build", "activate_practice", "refresh"})
    user = acting_user()
    take_uid = _required_text(arguments, "take_uid")
    if operation == "build":
        return service.build_take_resource(
            user, take_uid, research_uid=_optional_text(arguments, "research_uid")
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


def analyze_take(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services.analysis import critique_thesis_resource

    _operation(arguments, {"critique_thesis"})
    user = acting_user()
    take_uid = _required_text(arguments, "take_uid")
    return critique_thesis_resource(user, take_uid, mode=_optional_text(arguments, "research_mode"))


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


def accounts(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import accounts as service

    operation = _operation(arguments, {"list", "linkable", "link", "get", "holdings", "revoke"})
    user = acting_user()
    if operation == "list":
        return service.list_linked_accounts(
            user, include_revoked=bool(arguments.get("include_revoked", False))
        )
    if operation == "linkable":
        venue = _required_text(arguments, "venue")
        if venue not in VENUES:
            raise ValueError("venue must be alpaca or ibkr.")
        return service.linkable_accounts(user, venue)
    if operation == "link":
        return service.link_account_resource(user, _request_model(arguments, LinkAccountRequest))
    link_uid = _required_text(arguments, "link_uid")
    if operation == "get":
        return service.get_linked_account(user, link_uid)
    if operation == "holdings":
        return service.linked_account_holdings(
            user, link_uid, capture=bool(arguments.get("capture", False))
        )
    return service.revoke_linked_account(user, link_uid)


def funding(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import fundings as service

    operation = _operation(arguments, {"fund", "withdraw", "list", "get", "for_take"})
    user = acting_user()
    if operation == "list":
        return service.list_funding_resources(user)
    if operation == "get":
        return service.get_funding_resource(user, _required_text(arguments, "funding_uid"))
    take_uid = _required_text(arguments, "take_uid")
    if operation == "fund":
        return service.fund_take_resource(user, take_uid, _request_model(arguments, FundRequest))
    if operation == "withdraw":
        return service.withdraw_take_resource(user, take_uid)
    return service.take_funding_resource(user, take_uid)


def proposals(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import fundings as service

    operation = _operation(arguments, {"list", "get", "approve", "reject", "sync"})
    user = acting_user()
    if operation == "list":
        return service.list_proposal_resources(
            user,
            status=_optional_text(arguments, "status"),
            take_uid=_optional_text(arguments, "take_uid"),
            open_only=bool(arguments.get("open_only", False)),
        )
    proposal_uid = _required_text(arguments, "proposal_uid")
    if operation == "get":
        return service.get_proposal_resource(user, proposal_uid)
    if operation == "approve":
        return service.approve_proposal_resource(user, proposal_uid)
    if operation == "reject":
        return service.reject_proposal_resource(
            user, proposal_uid, reason=_optional_text(arguments, "reason")
        )
    return service.sync_proposal_resource(user, proposal_uid)


def reviews(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services import reviews as service

    operation = _operation(arguments, {"run", "list"})
    user = acting_user()
    take_uid = _required_text(arguments, "take_uid")
    if operation == "run":
        return service.run_review_resource(
            user, take_uid, mode=_optional_text(arguments, "research_mode")
        )
    limit, _ = _page(arguments, maximum=365)
    return service.list_review_resources(user, take_uid, limit=limit)


def leaderboard(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services.community import leaderboard_response

    _operation(arguments, {"get"})
    acting_user()
    limit, _ = _page(arguments, maximum=200)
    return leaderboard_response(limit=limit)


def notifications(arguments: Mapping[str, Any]) -> Any:
    from hunch.api.app.identity import acting_user
    from hunch.api.app.services.community import mark_read_response, notifications_response

    operation = _operation(arguments, {"list", "mark_read"})
    user = acting_user()
    if operation == "list":
        limit, _ = _page(arguments, maximum=200)
        return notifications_response(
            user, unread_only=bool(arguments.get("unread_only", False)), limit=limit
        )
    uids = arguments.get("uids")
    if uids is not None and not isinstance(uids, list):
        raise ValueError("uids must be a list of notification uids.")
    return mark_read_response(user, [str(uid) for uid in uids] if uids is not None else None)


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
                    "email_digest": {
                        "type": "boolean",
                        "description": "Opt in or out of the daily email digest.",
                    },
                    "email_address": _string("Digest address; empty to use the platform email."),
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
        name="hunch_research_take",
        label="Research A Take",
        description=(
            "Research an owned take's thesis against the target universe: the candidate "
            "instruments with their roles, cases, risks and conviction, a brief and a rationale, "
            "kept as the take's next numbered research. Decides no weight and changes no "
            "portfolio: build the take from it with hunch_build_take. Hosted research returns a "
            "JobRun UID to follow. `list` and `get` read the research a take keeps (owned or "
            "published)."
        ),
        parameters=_operations(
            _operation_case(
                "run",
                properties={
                    "take_uid": _uid("take"),
                    "research_mode": _enum(
                        RESEARCH_MODES, "Override the configured research mode."
                    ),
                },
                required=("take_uid",),
            ),
            _operation_case(
                "list",
                properties={
                    "take_uid": _uid("take"),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                },
                required=("take_uid",),
            ),
            _operation_case(
                "get",
                properties={"take_uid": _uid("take"), "research_uid": _uid("research")},
                required=("take_uid", "research_uid"),
            ),
        ),
        execution_mode="sequential",
        handler=research_take,
        timeout_seconds=BUILD_TOOL_TIMEOUT_SECONDS,
    ),
    ProjectAgentTool(
        name="hunch_build_take",
        label="Build A Take",
        description=(
            "Portfolio construction of an owned take from a stored research (its latest, or "
            "`research_uid`): apply its constraints, publish the weights and compute the "
            "portfolio; then activate it as a practice take or refresh its values. No model is "
            "called; research the take first. Hosted builds return a JobRun UID to follow."
        ),
        parameters=_operations(
            _operation_case(
                "build",
                properties={
                    "take_uid": _uid("take"),
                    "research_uid": _uid("research to construct from (the latest by default)"),
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
        name="hunch_analyze_take",
        label="Analyze A Take",
        description=(
            "Analysis only, nothing changes: critique the thesis of a take the person owns or a "
            "published one with one bounded call on the analysis model. Returns the claims with "
            "their strength, the assumptions, counterarguments, risks, conditions that would show "
            "the thesis wrong, tensions with the constraints and questions that would sharpen it. "
            "Useful before a build or before publishing."
        ),
        parameters=_operations(
            _operation_case(
                "critique_thesis",
                properties={
                    "take_uid": _uid("take"),
                    "research_mode": _enum(RESEARCH_MODES, "Override the configured mode."),
                },
                required=("take_uid",),
            ),
        ),
        execution_mode="parallel",
        handler=analyze_take,
        timeout_seconds=ANALYSIS_TOOL_TIMEOUT_SECONDS,
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
        name="hunch_accounts",
        label="Linked Accounts",
        description=(
            "The person's linked brokerage accounts: list them, see which connector-registered "
            "accounts could be linked, link one (keys are entered on the connector's site, never "
            "here), read its holdings, or revoke the link."
        ),
        parameters=_operations(
            _operation_case(
                "list",
                properties={
                    "include_revoked": {"type": "boolean", "description": "Include revoked links."}
                },
            ),
            _operation_case(
                "linkable",
                properties={"venue": _enum(VENUES, "alpaca or ibkr.")},
                required=("venue",),
            ),
            _operation_case(
                "link",
                properties={"request": _request(LinkAccountRequest, "The account to link.")},
                required=("request",),
            ),
            _operation_case("get", properties={"link_uid": _uid("link")}, required=("link_uid",)),
            _operation_case(
                "holdings",
                properties={
                    "link_uid": _uid("link"),
                    "capture": {
                        "type": "boolean",
                        "description": "Ask the connector for a fresh snapshot first.",
                    },
                },
                required=("link_uid",),
            ),
            _operation_case(
                "revoke", properties={"link_uid": _uid("link")}, required=("link_uid",)
            ),
        ),
        execution_mode="sequential",
        handler=accounts,
    ),
    ProjectAgentTool(
        name="hunch_funding",
        label="Fund A Take",
        description=(
            "Fund a built take into a linked account (approval or autopilot), withdraw it back to "
            "cash, or read fundings with NAV, cash, positions and return on the funded notional. "
            "Funding and withdrawing move real money: act only on the person's explicit go-ahead."
        ),
        parameters=_operations(
            _operation_case(
                "fund",
                properties={
                    "take_uid": _uid("take"),
                    "request": _request(FundRequest, "Account, notional, mode and policy."),
                },
                required=("take_uid", "request"),
            ),
            _operation_case(
                "withdraw", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
            _operation_case("list"),
            _operation_case(
                "get", properties={"funding_uid": _uid("funding")}, required=("funding_uid",)
            ),
            _operation_case(
                "for_take", properties={"take_uid": _uid("take")}, required=("take_uid",)
            ),
        ),
        execution_mode="sequential",
        handler=funding,
        timeout_seconds=BUILD_TOOL_TIMEOUT_SECONDS,
    ),
    ProjectAgentTool(
        name="hunch_proposals",
        label="Trade Proposals",
        description=(
            "Trade proposals of the person's funded takes: list or read them (legs, trigger, "
            "status, autopilot check, order states), approve one so the venue connector executes "
            "it, reject one, or sync its order states. Approve only on the person's explicit word."
        ),
        parameters=_operations(
            _operation_case(
                "list",
                properties={
                    "status": _enum(PROPOSAL_STATUSES, "Only proposals in this status."),
                    "take_uid": _uid("take"),
                    "open_only": {"type": "boolean", "description": "Only unsettled proposals."},
                },
            ),
            _operation_case(
                "get", properties={"proposal_uid": _uid("proposal")}, required=("proposal_uid",)
            ),
            _operation_case(
                "approve",
                properties={"proposal_uid": _uid("proposal")},
                required=("proposal_uid",),
            ),
            _operation_case(
                "reject",
                properties={
                    "proposal_uid": _uid("proposal"),
                    "reason": _string("Why the person rejects it."),
                },
                required=("proposal_uid",),
            ),
            _operation_case(
                "sync", properties={"proposal_uid": _uid("proposal")}, required=("proposal_uid",)
            ),
        ),
        execution_mode="sequential",
        handler=proposals,
        timeout_seconds=BUILD_TOOL_TIMEOUT_SECONDS,
    ),
    ProjectAgentTool(
        name="hunch_reviews",
        label="Daily Reviews",
        description=(
            "Run today's review of a take (drift, thesis check, proposal when funded) or list "
            "its past reviews."
        ),
        parameters=_operations(
            _operation_case(
                "run",
                properties={
                    "take_uid": _uid("take"),
                    "research_mode": _enum(RESEARCH_MODES, "Override the configured mode."),
                },
                required=("take_uid",),
            ),
            _operation_case(
                "list",
                properties={"take_uid": _uid("take"), **_page_properties(maximum=365)},
                required=("take_uid",),
            ),
        ),
        execution_mode="sequential",
        handler=reviews,
        timeout_seconds=BUILD_TOOL_TIMEOUT_SECONDS,
    ),
    ProjectAgentTool(
        name="hunch_leaderboard",
        label="Leaderboard",
        description="Published takes ranked by return since activation (practice results are simulated).",
        parameters=_operations(_operation_case("get", properties=_page_properties(maximum=200))),
        execution_mode="parallel",
        handler=leaderboard,
    ),
    ProjectAgentTool(
        name="hunch_notifications",
        label="Notifications",
        description="The person's notification feed: list it (optionally unread only) or mark it read.",
        parameters=_operations(
            _operation_case(
                "list",
                properties={
                    "unread_only": {"type": "boolean", "description": "Only unread items."},
                    **_page_properties(maximum=200),
                },
            ),
            _operation_case(
                "mark_read",
                properties={
                    "uids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Notification uids; omit to mark everything read.",
                    }
                },
            ),
        ),
        execution_mode="sequential",
        handler=notifications,
    ),
    ProjectAgentTool(
        name="hunch_get_job_run_status",
        label="Get Hunch JobRun Status",
        description=(
            "Read one Hunch research, build or refresh JobRun status and its sanitized failure "
            "summary."
        ),
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
    "ANALYSIS_TOOL_TIMEOUT_SECONDS",
    "BUILD_TOOL_TIMEOUT_SECONDS",
    "PROJECT_AGENT_TOOLS",
    "ProjectAgentTool",
    "accounts",
    "analyze_take",
    "build_take",
    "funding",
    "get_job_run_status",
    "leaderboard",
    "manage_take",
    "notifications",
    "profile",
    "project_state",
    "proposals",
    "query_instruments",
    "query_portfolio",
    "query_takes",
    "research_take",
    "reviews",
]
