"""Local MCP transport only; hosted application tools are supplied by Tau from the workflow."""

from api.tau.local_mcp import local_mcp_tools


def setup(tau) -> None:
    for tool in local_mcp_tools():
        tau.register_tool(tool)
