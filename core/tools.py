import os
import ast
import importlib.util
import re
import json
import glob
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from core.memory_db import query_test_history as _query_history, log_healing_action as _log_healing
from knowledge_graph.graph_query import (
    query_risk_propagation,
    query_similar_defects,
    query_healing_patterns,
    query_component_health,
)

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
CHROMA_PATH = str(ROOT / "codebase_db")
TESTS_DIR = ROOT / "tests"
TEMPLATES_DIR = ROOT / "demo_app" / "templates"
REPORTS_DIR = ROOT / "reports"


@tool
def read_requirements_file(file_path: str) -> str:
    """Read the project requirements markdown file to understand the scope of testing.

    Args:
        file_path: The path to the requirements file (e.g., 'project_requirements.md')
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

_vectorstore = None

def _get_vectorstore():
    global _vectorstore
    if _vectorstore is None:
        embeddings = OllamaEmbeddings(
            model=os.environ.get('OLLAMA_EMBEDDING_MODEL', 'nomic-embed-text'),
            base_url=os.environ.get('OLLAMA_ENDPOINT', 'http://localhost:11434'),
        )
        _vectorstore = Chroma(
            persist_directory=CHROMA_PATH,
            embedding_function=embeddings,
        )
    return _vectorstore

@tool
def search_codebase(query: str) -> str:
    """Search the codebase vector database for relevant source code.

    Use this to find implementation details, function signatures,
    class definitions, HTML templates, and API route handlers
    before generating tests.

    Args:
        query: Natural language description of what code to find.
    """
    
    try:
        vectorstore = _get_vectorstore()
        retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
        docs = retriever.invoke(query)
        return "\n\n---\n\n".join(
            f"**Source: {doc.metadata.get('source', 'unknown')}**\n{doc.page_content}"
            for doc in docs
        )
    except Exception as e:
        return f"Error querying codebase database: {e}"


@tool
def validate_python_syntax(code: str) -> str:
    """Validate that generated Python code is syntactically correct."""
    try:
        ast.parse(code)
        return "Syntax is valid."
    except SyntaxError as e:
        return f"Syntax error at line {e.lineno}: {e.msg}\n{e.text}"


@tool
def validate_imports(code: str) -> str:
    """Check that all imports in the generated code resolve to installed or local modules."""
    tree = ast.parse(code)
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if not importlib.util.find_spec(module):
                    issues.append(f"Module '{alias.name}' not found")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module.split(".")[0]
                if not importlib.util.find_spec(module):
                    issues.append(f"Module '{node.module}' not found")
    if issues:
        return "Import issues:\n" + "\n".join(f"  - {i}" for i in issues)
    return "All imports are valid."


@tool
def check_test_structure(code: str) -> str:
    """Verify that the generated code contains valid pytest test functions."""
    tree = ast.parse(code)
    test_functions, issues = [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            test_functions.append(node.name)
            has_assert = any(
                isinstance(child, ast.Assert)
                or (isinstance(child, ast.With) and any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Attribute)
                    and item.context_expr.func.attr == "raises"
                    for item in (child.items if hasattr(child, 'items') else [])
                ))
                or (isinstance(child, ast.Expr) and isinstance(child.value, ast.Call)
                    and isinstance(child.value.func, ast.Attribute)
                    and child.value.func.attr.startswith("assert"))
                for child in ast.walk(node)
            )
            if not has_assert:
                issues.append(f"'{node.name}' has no assert statement")
    if not test_functions:
        return "No test functions found. Test functions must start with 'test_'."
    result = f"Found {len(test_functions)} test functions: {', '.join(test_functions)}"
    if issues:
        result += "\nWarnings:\n" + "\n".join(f"  - {i}" for i in issues)
    return result


@tool
def write_test_file(file_name: str, test_code: str) -> str:
    """Write generated pytest code to a file in the tests/ directory."""
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = os.path.basename(file_name)
    if not safe_name.endswith(".py"):
        return f"Refused: '{file_name}' must end in .py"
    path = TESTS_DIR / safe_name
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(test_code)
        return f"Wrote {len(test_code)} chars to {path}"
    except Exception as e:
        return f"Failed to write {path}: {e}"


@tool
def run_pytest_suite(target: str) -> str:
    """Run pytest on the given target (file or directory) and return the output.

    Args:
        target: Path to the test file or directory, relative to project root (e.g. 'tests/' or 'tests/test_auth.py').
    """
    path = ROOT / target
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", str(path), "-v", "--tb=short"], 
            capture_output=True, 
            text=True,
            timeout=120
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return output
    except subprocess.TimeoutExpired:
        return f"Execution of {target} timed out after 120 seconds."
    except Exception as e:
        return f"Failed to run pytest: {e}"

@tool
def check_environment_health() -> str:
    """Check the real-time health of the environment (e.g. database and server).
    
    Returns a JSON-like string with the status of runners and network.
    """
    db_path = ROOT / "demo_app" / "demo.db"
    db_connected = db_path.exists()
    
    server_status = "unreachable"
    base_url = os.environ.get('APP_BASE_URL', 'http://localhost:3000')
    try:
        response = urllib.request.urlopen(f"{base_url}/health", timeout=2)
        if response.status == 200:
            server_status = "healthy"
    except urllib.error.URLError:
        server_status = "unreachable"
    except Exception:
        pass
    
    return str({
        "runners_available": True,
        "db_connected": db_connected,
        "server_status": server_status,
        "base_url": base_url
    })


@tool
def write_report_file(file_name: str, content: str) -> str:
    """Write the final QA report to the reports/ directory.

    Args:
        file_name: The output file name (e.g. 'qa_report_run1.md'). Must end in .md or .html.
        content: The full report content in Markdown or HTML.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = os.path.basename(file_name)
    if not (safe_name.endswith(".md") or safe_name.endswith(".html")):
        return f"Refused: '{file_name}' must end in .md or .html"
    path = REPORTS_DIR / safe_name
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Report written to {path}"
    except Exception as e:
        return f"Failed to write report: {e}"


@tool
def get_timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@tool
def read_test_file(file_path: str) -> str:
    """Read the source code of a test file for root-cause analysis.

    Args:
        file_path: Path relative to project root (e.g. 'tests/test_auth.py').
    """
    path = ROOT / file_path
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"File not found: {file_path}"
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def search_git_log(keyword: str) -> str:
    """Search recent git commit messages for a keyword to correlate failures with code changes.

    NOTE: Defined for Phase 5 use. Not included in DEFECT_TOOLS until git-diff analysis
    is enabled. We are currently testing against requirements, not commit history.

    Args:
        keyword: The keyword to search for (e.g. a function name, module name, or error term).
    """
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-20", f"--grep={keyword}"],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        return result.stdout or "No recent commits matched."
    except Exception as e:
        return f"Git log search failed: {e}"


@tool
def read_server_log(max_lines: int = 50) -> str:
    """Read the last N lines of the application server log for error correlation.

    Args:
        max_lines: Number of lines from the end of the log to return (default 50).
    """
    log_candidates = [ROOT / "server.log", ROOT / "demo_app" / "server.log"]
    for log_path in log_candidates:
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                return "".join(lines[-max_lines:])
            except Exception as e:
                return f"Error reading log: {e}"
    return "No server log found. The application may not have been running during test execution."


@tool
def read_source_file(file_path: str) -> str:
    """Read any source file from the project for patching.

    Args:
        file_path: Relative path from project root (e.g. 'demo_app/auth.py' or 'tests/test_auth.py').
    """
    path = ROOT / file_path
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"File not found: {file_path}"
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def patch_file(file_path: str, old_code: str, new_code: str) -> str:
    """Replace a specific code snippet in a file with a corrected version.

    The tool finds the EXACT `old_code` substring in the file and replaces it with `new_code`.
    If `old_code` is not found verbatim, the patch fails safely.

    Args:
        file_path: Relative path from project root.
        old_code: The exact code snippet to replace (copy-paste from the file).
        new_code: The corrected code to insert in its place.
    """
    path = ROOT / file_path
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"FAIL: File not found: {file_path}"

    if old_code not in content:
        return (
            f"FAIL: old_code not found in {file_path}. "
            "Ensure you copied the exact text including whitespace."
        )

    occurrences = content.count(old_code)
    if occurrences > 1:
        return (
            f"FAIL: old_code appears {occurrences} times in {file_path}. "
            "Provide a larger snippet for unique matching."
        )

    new_content = content.replace(old_code, new_code, 1)
    path.write_text(new_content, encoding="utf-8")
    return f"SUCCESS: Patched {file_path} ({len(old_code)} chars -> {len(new_code)} chars)"


@tool
def run_single_test(test_path: str) -> str:
    """Run a single test file to verify a patch works.

    Args:
        test_path: Relative path to the test file (e.g. 'tests/test_auth.py').
    """
    path = ROOT / test_path
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", str(path), "-v", "--tb=short"],
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return output
    except subprocess.TimeoutExpired:
        return f"Timeout after 60s running {test_path}"
    except Exception as e:
        return f"Failed to run test: {e}"


@tool
def query_test_history(test_id: str) -> str:
    """Query the long-term memory database for historical execution data on a test.

    Returns flakiness rate, pass/fail counts, and average duration across all recorded runs.

    Args:
        test_id: Path to the test file (e.g. 'tests/test_auth.py').
    """
    return json.dumps(_query_history(test_id), indent=2)


@tool
def log_healing_action(
    anomaly_id: str,
    action_type: str,
    target_file: str = "",
    original_code: str = "",
    patched_code: str = "",
    explanation: str = "",
    success: bool = True,
) -> str:
    """Record a self-healing action in the long-term memory database.

    Call this after successfully patching a test or source file so the healing ledger
    tracks what was changed and why.

    Args:
        anomaly_id: The anomaly ID this healing addresses (e.g. 'ANOM-001').
        action_type: One of 'SELF_HEAL_LOCATOR', 'SELF_HEAL_LOGIC', 'ESCALATE_HUMAN', 'NO_ACTION'.
        target_file: Relative path to the file that was modified.
        original_code: The code snippet that was replaced.
        patched_code: The new code snippet written.
        explanation: Plain-English explanation of the fix.
        success: Whether the patch was applied successfully.
    """
    _log_healing(
        anomaly_id=anomaly_id,
        action_type=action_type,
        target_file=target_file,
        original_code=original_code,
        patched_code=patched_code,
        explanation=explanation,
        success=success,
    )
    return f"Healing action for {anomaly_id} logged successfully."


PLANNING_TOOLS = [read_requirements_file, query_risk_propagation]
UNIT_TOOLS= [search_codebase, validate_python_syntax, validate_imports, check_test_structure, write_test_file]
INTEGRATION_TOOLS = [search_codebase, validate_python_syntax, validate_imports, check_test_structure, write_test_file]
E2E_TOOLS = [search_codebase, validate_python_syntax, validate_imports, check_test_structure, write_test_file]
EXECUTION_TOOLS = [run_pytest_suite, check_environment_health, query_test_history]
REPORTING_TOOLS = [write_report_file, get_timestamp, query_component_health]
DEFECT_TOOLS = [search_codebase, read_test_file, read_server_log, query_test_history, query_similar_defects]
SELF_HEALING_TOOLS = [search_codebase, read_source_file, read_test_file, patch_file, run_single_test, validate_python_syntax, log_healing_action, query_test_history, query_healing_patterns]
