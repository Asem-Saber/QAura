"""Unified MCP server configuration for QAura agents.

Builds a MultiServerMCPClient-compatible config dict containing
any combination of Playwright (browser automation) and lean-ctx
(context-compressed code reading/search) MCP servers.
"""

import os


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
