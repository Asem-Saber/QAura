# core/tools.py
"""LangChain tool definitions for QAura.

Contains tools used by the Unit Test Generator. Tools for other agents
will be added here as they are implemented.
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

    Returns the file path string, or an error message starting with
    "ERROR:".
    """
    parts = module.split(".")
    candidate = Path(project_root) / Path(*parts)

    py_file = candidate.with_suffix(".py")
    if py_file.exists():
        return str(py_file)

    init_file = candidate / "__init__.py"
    if init_file.exists():
        return str(init_file)

    return f"ERROR: Cannot resolve module '{module}' under {project_root}"

@tool
def read_source_file(file_path: str) -> str:
    """Read a Python source file and return its contents.

    Args:
        file_path: Absolute or relative path to the .py file.

    Returns:
        The file contents as a string, or an error message starting
        with "ERROR:".
    """
    path = Path(file_path)
    if not path.exists():
        return f"ERROR: File not found: {file_path}"
    return path.read_text(encoding="utf-8")

# ── AST Parsing Tool ───────────────────────────────────────────────────

@tool
def parse_ast(source_code: str, module_path: str) -> str:
    """Parse Python source code and return all testable symbols.

    Discovers functions, classes, and methods with their signatures,
    decorators, and docstrings. Returns a formatted string inventory
    suitable for feeding to an LLM.

    Args:
        source_code: The Python source code to parse.
        module_path: The dotted module path (for reference in output).

    Returns:
        A formatted string listing all symbols, or "(no symbols
        found)" if the source has no testable units.
    """
    tree = ast.parse(source_code)
    lines: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent = _find_parent_class(tree, node)
            prefix = f"{parent}." if parent else ""
            params = _extract_params(node)
            ret = ""
            if node.returns:
                try:
                    ret = f" -> {ast.unparse(node.returns)}"
                except Exception:
                    pass
            kind = "method" if parent else "function"
            lines.append(
                f"- {kind}: {prefix}{node.name}({', '.join(params)}){ret}"
            )
            doc = ast.get_docstring(node)
            if doc:
                lines.append(f"    doc: {doc[:120]}")
        elif isinstance(node, ast.ClassDef):
            init_params = _extract_init_params(node)
            lines.append(
                f"- class: {node.name}({', '.join(init_params)})"
            )
            doc = ast.get_docstring(node)
            if doc:
                lines.append(f"    doc: {doc[:120]}")

    return "\n".join(lines) if lines else "(no symbols found)"

# ── Syntax Validation Tool ─────────────────────────────────────────────

@tool
def validate_syntax(code: str) -> str:
    """Validate that Python code is syntactically correct.

    Performs two checks:
        1. ast.parse — catches syntax errors
        2. py_compile — catches compile-time issues

    Args:
        code: The Python source code to validate.

    Returns:
        "VALID" if the code parses and compiles, or "INVALID: <error>"
        with a description of the issue.
    """
    # Fast path: AST parse
    try:
        ast.parse(code)
    except SyntaxError as e:
        return (
            f"INVALID: SyntaxError: {e.msg} (line {e.lineno})"
        )

    # Deeper check: compile
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        py_compile.compile(tmp_path, doraise=True)
        return "VALID"
    except py_compile.PyCompileError as e:
        return f"INVALID: {e}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)

# ── Collaborator Discovery Tool ────────────────────────────────────────

_EXTERNAL_HINTS = {
    "requests",
    "httpx",
    "aiohttp",
    "psycopg",
    "sqlalchemy",
    "redis",
    "boto3",
    "pymongo",
    "celery",
    "kafka",
}

@tool
def discover_collaborators(source_code: str, module_path: str) -> str:
    """Analyze source code to find mockable dependency seams.

    Looks for:
        - __init__ parameters with type hints (constructor injection)
        - Top-level imports of external services (db, http, cache, etc.)

    Args:
        source_code: The Python source code to analyze.
        module_path: The dotted module path (for reference).

    Returns:
        A formatted string listing collaborators to mock, or "(no
        collaborators found)".
    """
    tree = ast.parse(source_code)
    lines: list[str] = []
    seen: set[str] = set()

    # Constructor parameters
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef)
                    and child.name == "__init__"
                ):
                    for arg in child.args.args[1:]:  # skip self
                        if arg.arg not in seen:
                            hint = ""
                            if arg.annotation:
                                try:
                                    hint = (
                                        f" [{ast.unparse(arg.annotation)}]"
                                    )
                                except Exception:
                                    pass
                            lines.append(
                                f"- {arg.arg} (constructor_param){hint}"
                            )
                            seen.add(arg.arg)

    # Module-level imports that look like external dependencies
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _EXTERNAL_HINTS and alias.name not in seen:
                    lines.append(
                        f"- {alias.asname or alias.name} (import) "
                        f"<- {alias.name}"
                    )
                    seen.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in _EXTERNAL_HINTS:
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name not in seen:
                        lines.append(
                            f"- {name} (import) <- {node.module}"
                        )
                        seen.add(name)

    return (
        "\n".join(lines) if lines else "(no collaborators found)"
    )

# ── Fixture Lookup Tool ────────────────────────────────────────────────

@tool
def lookup_existing_fixtures(conftest_path: str) -> str:
    """Read a conftest.py file and return existing pytest fixtures.

    Parses the file for @pytest.fixture decorated functions and
    returns their names, scopes, and parameters. This lets the
    generator reuse existing fixtures instead of duplicating them.

    Args:
        conftest_path: Path to the conftest.py file.

    Returns:
        A formatted string listing fixtures, "(no fixtures found)"
        if the file has none, or "(no conftest.py found)" if the
        file doesn't exist.
    """
    p = Path(conftest_path)
    if not p.exists():
        return "(no conftest.py found)"

    source = p.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            try:
                dec_str = ast.unparse(dec)
            except Exception:
                continue
            if "fixture" not in dec_str:
                continue

            scope = "function"
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "scope":
                        try:
                            scope = (
                                ast.unparse(kw.value).strip("'\"")
                            )
                        except Exception:
                            pass

            params = [arg.arg for arg in node.args.args]
            lines.append(
                f"- @{scope}: {node.name}({', '.join(params)})"
            )

    return "\n".join(lines) if lines else "(no fixtures found)"

# ── Internal Helpers ───────────────────────────────────────────────────

def _extract_params(node: ast.FunctionDef) -> list[str]:
    """Extract parameter names from a function definition."""
    params = [arg.arg for arg in node.args.args]
    if node.args.vararg:
        params.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        params.append(f"**{node.args.kwarg.arg}")
    return params

def _extract_init_params(node: ast.ClassDef) -> list[str]:
    """Extract __init__ parameter names from a class (excluding self)."""
    for child in node.body:
        if (
            isinstance(child, ast.FunctionDef)
            and child.name == "__init__"
        ):
            return [
                arg.arg for arg in child.args.args if arg.arg != "self"
            ]
    return []

def _find_parent_class(tree: ast.AST, target: ast.AST) -> str | None:
    """Find the class name that contains a given function node."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if child is target:
                    return node.name
    return None

# ── Semantic Search Tools ──────────────────────────────────────────────

@tool
def semantic_search(
    query: str,
    project_root: str = ".",
    k: int = 5,
) -> str:
    """Search the codebase for code relevant to a natural language query.

    Uses semantic similarity over an embedded index of the codebase
    (Python, HTML, JS, etc.) to find relevant code chunks. The index
    is built automatically on first use and persisted to disk.

    Useful for:
        - Finding how a component is used elsewhere
        - Discovering existing test patterns to follow
        - Locating similar implementations
        - Understanding cross-module dependencies

    Args:
        query: Natural language search query
            (e.g. "how is UserService created and used").
        project_root: Root directory of the codebase to search.
        k: Number of results to return (default 5).

    Returns:
        Formatted string with code chunks and their file sources,
        or "(no results found)".
    """
    from core.codebase_index import get_index

    try:
        index = get_index(project_root=project_root)
        return index.search_formatted(query, k=k)
    except FileNotFoundError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: Semantic search failed: {e}"

'''
@tool
def index_codebase(
    project_root: str = ".",
    file_types: str | None = None,
) -> str:
    """Index or re-index the codebase for semantic search.

    Loads all supported file types from the project root, splits them
    into chunks, embeds them, and stores them in a persistent Chroma
    vectorstore. Call this before semantic_search if the codebase
    has changed.

    Args:
        project_root: Root directory of the codebase to index.
        file_types: Comma-separated list of file types to index
            (e.g. "python,html"). If None, indexes all supported types.

    Returns:
        Summary message with the number of chunks indexed.
    """
    from core.codebase_index import get_index

    types_list = None
    if file_types:
        types_list = [t.strip() for t in file_types.split(",")]

    try:
        index = get_index(
            project_root=project_root,
            force_new=True,
        )
        if types_list:
            index.file_types = types_list
        count = index.index()
        return f"Indexed {count} chunks from {project_root}"
    except FileNotFoundError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: Indexing failed: {e}"

@tool
def codebase_stats(project_root: str = ".") -> str:
    """Return statistics about the codebase search index.

    Shows whether the codebase is indexed, how many documents are
    in the vectorstore, and what embedding model is being used.

    Args:
        project_root: Root directory of the codebase.

    Returns:
        Formatted string with index statistics.
    """
    from core.codebase_index import get_index

    try:
        index = get_index(project_root=project_root)
        stats = index.get_stats()
        return (
            f"Indexed: {stats['indexed']}\n"
            f"Documents: {stats['document_count']}\n"
            f"Persist dir: {stats['persist_dir']}\n"
            f"Embedding model: {stats['embedding_model']}\n"
            f"Endpoint: {stats['endpoint']}"
        )
    except Exception as e:
        return f"ERROR: {e}"
        
    '''