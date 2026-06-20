# core/tools.py
"""LangChain tool definitions for QAura.

Currently contains tools used by the Unit Test Generator. Tools for
other agents will be added here as they are implemented.
"""

from __future__ import annotations

import ast
import py_compile
import tempfile
from pathlib import Path

from langchain_core.tools import tool

# ── Source Discovery Tools ─────────────────────────────────────────────

@tool
def resolve_module_path(module: str, project_root: str) -> str:
    """Convert a dotted module path to a filesystem path.

    Examples:
        "auth.service" with root "." -> "auth/service.py"
        "auth" with root "src" -> "src/auth/__init__.py"

    Returns the file path string, or an error message starting with "ERROR:".
    """
    parts = module.split(".")
    candidate = Path(project_root) / Path(*parts)

    py_file = candidate.with_suffix(".py")
    if py_file.exists():
        return str(py_file)

    init_file = candidate / "__init__.py"
    if init_file.exists():
        return str