"""Local-only MCP bridge for the Hunch Agent; schemas and business rules live in the API.

Hosted, the platform resolves the workflow's `mcp_applications` and Tau registers `hunch__*`
tools itself. A local Tau bootstrap resolves no applications, so this bridge registers the same
four tool names and forwards them to the loopback Hunch API's `/mcp`, which presents the
developer's own sign-in. It loads only when `TAU_LOCAL_MODE` is set and refuses a hosted runtime.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult

MAX_RESULT_CHARS = 1_000_000
DEFAULT_API_ORIGIN = "http://127.0.0.1:8601"


class _Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Call(_Empty):
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict = Field(default_factory=dict)


class _Read(_Empty):
    uri: str = Field(min_length=1, max_length=512)


def _endpoint() -> str:
    origin = os.environ.get("HUNCH_LOCAL_API_ORIGIN", DEFAULT_API_ORIGIN)
    url = urlsplit(origin)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "::1", "localhost"}
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
        or url.port is None
    ):
        raise ValueError("HUNCH_LOCAL_API_ORIGIN must be an HTTP loopback origin with a port")
    return origin.rstrip("/") + "/mcp"


@asynccontextmanager
async def _session(endpoint: str):
    # No credentials are sent: the loopback Hunch launcher presents the developer's sign-in.
    async with httpx.AsyncClient(timeout=60, trust_env=False) as http:
        async with streamable_http_client(endpoint, http_client=http) as (read, write, *_rest):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def _result(data) -> AgentToolResult:
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        data = {"code": "result_too_large", "message": "Narrow the Hunch query"}
        text = json.dumps(data)
    return AgentToolResult(content=[TextContent(text=text)], details=data)


def local_mcp_tools() -> tuple[AgentTool, ...]:
    if os.environ.get("TAU_LOCAL_MODE", "").lower() not in {"true", "1", "yes", "on"}:
        return ()
    if os.environ.get("APP_NAME") or os.environ.get("MAINSEQUENCE_CALLER_AUTH_MODE") == "assertion":
        raise ValueError("The local Hunch bridge cannot run in a hosted runtime")
    endpoint = _endpoint()

    def tool(name: str, model: type[BaseModel], *, operation: str, description: str) -> AgentTool:
        mutating = operation == "call_tool"

        async def execute(tool_call_id, arguments, signal=None, on_update=None):
            del tool_call_id, on_update
            try:
                parsed = model.model_validate(dict(arguments))
            except (ValidationError, TypeError, ValueError):
                return _result({"code": "invalid_arguments"})
            if signal is not None and signal.is_cancelled():
                return _result({"code": "cancelled", "message": "The call was not started"})
            sent = False
            try:
                with anyio.fail_after(90):
                    async with _session(endpoint) as session:
                        if signal is not None and signal.is_cancelled():
                            return _result({"code": "cancelled"})
                        if operation == "call_tool":
                            sent = True
                            raw = await session.call_tool(parsed.tool, parsed.arguments)
                        elif operation == "list_tools":
                            raw = await session.list_tools()
                        elif operation == "list_resources":
                            raw = await session.list_resources()
                        else:
                            raw = await session.read_resource(parsed.uri)
                        data = raw.model_dump(mode="json", exclude_none=True, by_alias=True)
            except Exception:
                # No retry: a failed response may follow a committed write.
                return _result(
                    {
                        "code": "outcome_unknown" if sent else "unavailable",
                        "message": (
                            "Read current Hunch state before retrying; the call may have completed"
                            if sent
                            else "The local Hunch MCP endpoint is unavailable"
                        ),
                    }
                )
            if signal is not None and signal.is_cancelled():
                return _result(
                    {
                        "code": "outcome_unknown" if sent else "cancelled",
                        "message": "Read current Hunch state before any retry",
                    }
                )
            return _result(data)

        return AgentTool(
            name=name,
            label=name,
            description=description,
            parameters=model.model_json_schema(),
            execute_fn=execute,
            execution_mode="sequential" if mutating else "parallel",
        )

    return (
        tool(
            "hunch__list_tools",
            _Empty,
            operation="list_tools",
            description="List the Hunch application's MCP tools and input schemas.",
        ),
        tool(
            "hunch__call_tool",
            _Call,
            operation="call_tool",
            description="Call a Hunch MCP tool by name; use hunch__list_tools for its input schema.",
        ),
        tool(
            "hunch__list_resources",
            _Empty,
            operation="list_resources",
            description="List the skills the Hunch application publishes (skill:// resources).",
        ),
        tool(
            "hunch__read_resource",
            _Read,
            operation="read_resource",
            description="Read one published Hunch skill file by its skill:// URI.",
        ),
    )


__all__ = ["DEFAULT_API_ORIGIN", "local_mcp_tools"]
