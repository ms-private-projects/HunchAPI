"""The Hunch MCP server exposes the project tool catalog with safe errors."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import anyio

from hunch.agent_tools import PROJECT_AGENT_TOOLS
from hunch.api.app.identity import ActingUser
from hunch.api.app.mcp_server import MCP_SERVER_NAME, build_mcp_server
from hunch.takes import Take


def _call(server, name, arguments):
    return anyio.run(server.call_tool, name, arguments)


def _payload(result) -> dict:
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


def test_catalog_lists_the_project_tools_with_their_schemas() -> None:
    server = build_mcp_server()
    assert MCP_SERVER_NAME == "hunch"
    tools = anyio.run(server.list_tools)
    assert {tool.name for tool in tools} == {definition.name for definition in PROJECT_AGENT_TOOLS}
    assert {tool.name for tool in tools} == {
        "hunch_project_state",
        "hunch_profile",
        "hunch_query_takes",
        "hunch_manage_take",
    }
    by_name = {tool.name: tool for tool in tools}
    assert by_name["hunch_query_takes"].input_schema["oneOf"]
    assert by_name["hunch_query_takes"].annotations.read_only_hint
    assert not by_name["hunch_manage_take"].annotations.read_only_hint
    create_case = by_name["hunch_manage_take"].input_schema["oneOf"][0]
    assert "$ref" not in str(create_case) and "thesis_text" in str(create_case)


def test_unknown_tool_is_a_safe_error() -> None:
    result = _call(build_mcp_server(), "hunch_place_order", {"symbol": "AAPL"})
    assert result.is_error
    payload = _payload(result)
    assert payload["code"] == "unknown_tool"
    assert "AAPL" not in result.content[0].text


def test_schema_violations_never_echo_arguments() -> None:
    result = _call(build_mcp_server(), "hunch_query_takes", {"operation": "get"})
    assert result.is_error
    payload = _payload(result)
    assert payload["code"] == "invalid_request"
    assert "take_uid" not in json.dumps(payload["details"]).replace("required", "")


def test_project_state_returns_capabilities_and_configuration() -> None:
    with (
        patch("hunch.api.app.services.project_state.resolve_site_agent", return_value=None),
        patch("hunch.api.app.identity.bound_acting_user_uid", return_value="user-1"),
    ):
        result = _call(build_mcp_server(), "hunch_project_state", {})
    assert not result.is_error
    payload = _payload(result)
    assert payload["configuration"]["request_user_uid"] == "user-1"
    assert payload["configuration"]["venues"] == ["alpaca", "ibkr"]
    assert {item["key"] for item in payload["capabilities"]} >= {"takes", "portfolios"}


def test_query_takes_lists_only_the_acting_users_takes_and_reads_public_ones() -> None:
    mine = Take(uid=uuid.uuid4(), owner_user_uid="user-1", title="Mine", thesis_text="a")
    theirs_public = Take(
        uid=uuid.uuid4(),
        owner_user_uid="user-2",
        title="Public",
        thesis_text="b",
        visibility="public",
    )
    theirs_private = Take(uid=uuid.uuid4(), owner_user_uid="user-2", title="P", thesis_text="c")
    by_uid = {row.uid: row for row in (mine, theirs_public, theirs_private)}

    def fake_filter(*, limit=500, **filters):
        del limit
        return [row for row in by_uid.values() if row.owner_user_uid == filters["owner_user_uid"]]

    with (
        patch("hunch.api.app.identity.acting_user", return_value=ActingUser("user-1", None)),
        patch("hunch.api.app.services.takes.profiles_by_uid", return_value={}),
        patch.object(Take, "filter", side_effect=fake_filter),
        patch.object(Take, "get_by_uid", side_effect=lambda uid: by_uid.get(uid)),
    ):
        server = build_mcp_server()
        listed = _payload(_call(server, "hunch_query_takes", {"operation": "list"}))
        assert [item["title"] for item in listed["items"]] == ["Mine"]
        assert listed["pageInfo"]["totalItems"] == 1

        public = _call(
            server, "hunch_query_takes", {"operation": "get", "take_uid": str(theirs_public.uid)}
        )
        assert not public.is_error
        assert _payload(public)["title"] == "Public"

        private = _call(
            server, "hunch_query_takes", {"operation": "get", "take_uid": str(theirs_private.uid)}
        )
        assert private.is_error
        assert _payload(private)["status_code"] == 404

        bad_page = _call(
            server, "hunch_query_takes", {"operation": "list", "limit": 10, "offset": 5}
        )
        assert bad_page.is_error
        assert _payload(bad_page)["code"] == "action_conflict"
