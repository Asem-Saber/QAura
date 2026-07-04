"""QAura development server entry point.

Uvicorn forces WindowsSelectorEventLoop on Windows, which does NOT support
subprocess spawning.  QAura agents need subprocesses for MCP servers
(lean-ctx, Playwright).  This script sets WindowsProactorEventLoop before
uvicorn starts, and passes loop='none' so uvicorn doesn't override it.

Usage:
    python run.py                        # default: port 8000, reload on
    python run.py --port 9000            # custom port
    python run.py --no-reload            # disable auto-reload
"""

import asyncio
import logging
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

logger = logging.getLogger("uvicorn.error")


def _windows_exception_handler(loop, context):
    exc = context.get("exception")
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 87:
        logger.debug("Suppressed known ProactorEventLoop accept error (WinError 87)")
        return
    loop.default_exception_handler(context)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="QAura dev server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        loop = asyncio.new_event_loop()
        loop.set_exception_handler(_windows_exception_handler)
        asyncio.set_event_loop(loop)

    uvicorn.run(
        "web.app:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        loop="none",
    )
