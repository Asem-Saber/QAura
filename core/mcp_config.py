"""Unified MCP server configuration for QAura agents.

Builds a MultiServerMCPClient-compatible config dict containing
any combination of Playwright (browser automation) and lean-ctx
(context-compressed code reading/search) MCP servers.
"""

import os
from contextlib import AsyncExitStack, asynccontextmanager

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools


def get_mcp_config(*, playwright: bool = False, leanctx: bool = True) -> dict:
    """Return MCP server configs for the requested servers.

    Args:
        playwright: Include Playwright browser automation server.
        leanctx: Include lean-ctx context compression server.
    """
    config = {}

    if playwright:
        headless = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
        pw_args = ["-y", "@playwright/mcp@latest", "--browser", "chromium"]
        if headless:
            pw_args.append("--headless")
        config["playwright"] = {
            "transport": "stdio",
            "command": "npx",
            "args": pw_args,
        }

    if leanctx and os.environ.get("LEAN_CTX_DISABLED") != "1":
        config["lean-ctx"] = {
            "transport": "stdio",
            "command": "lean-ctx",
            "args": [],
        }

    return config


@asynccontextmanager
async def open_mcp_tools(*, playwright: bool = False, leanctx: bool = True):
    """Yield LangChain tools backed by MCP sessions that live for the block.

    langchain-mcp-adapters >=0.1 removed context-manager support on
    MultiServerMCPClient, and its `get_tools()` opens a fresh session per
    tool CALL — which would break stateful Playwright flows (navigate, then
    snapshot the same page). So we hold one session per server for the
    duration of the agent node and load tools from those sessions.
    """
    config = get_mcp_config(playwright=playwright, leanctx=leanctx)
    client = MultiServerMCPClient(config)
    async with AsyncExitStack() as stack:
        tools = []
        for server_name in config:
            session = await stack.enter_async_context(client.session(server_name))
            tools.extend(await load_mcp_tools(session))
        yield tools
