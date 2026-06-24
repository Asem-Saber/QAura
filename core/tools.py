import os
import ast
import importlib.util
import re
import glob
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
CHROMA_PATH = str(ROOT / "codebase_db")
TESTS_DIR = ROOT / "tests"
TEMPLATES_DIR = ROOT / "demo_app" / "templates"


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

@tool
def search_codebase(query: str) -> str:
    """Search the codebase vector database for relevant source code.

    Use this to find implementation details, function signatures,
    class definitions, HTML templates, and API route handlers
    before generating tests.

    Args:
        query: Natural language description of what code to find.
    """

    embeddings = OllamaEmbeddings(
        model=os.environ['OLLAMA_EMBEDDING_MODEL'],
        base_url=os.environ['OLLAMA_ENDPOINT'],
    )

    vectorstore = Chroma(
        persist_directory=CHROMA_PATH,
        embedding_function=embeddings,
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
    docs = retriever.invoke(query)
    return "\n\n---\n\n".join(
        f"**Source: {doc.metadata.get('source', 'unknown')}**\n{doc.page_content}"
        for doc in docs
    )


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
                isinstance(child, ast.Assert) or isinstance(child, ast.With)
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
def validate_selenium_locators(test_code: str) -> str:
    """Check that data-testid selectors used in Selenium tests match actual attributes in the HTML templates."""
    used = set(re.findall(r"data-testid=['\"]([^'\"]+)['\"]", test_code))
    existing = set()
    for html_file in glob.glob(str(TEMPLATES_DIR / "*.html")):
        with open(html_file, "r", encoding="utf-8") as f:
            existing.update(re.findall(r'data-testid=["\']([^"\']+)["\']', f.read()))
    missing = used - existing
    if missing:
        return (
            "These data-testid values are NOT in the HTML templates:\n"
            + "\n".join(f"  - '{m}'" for m in sorted(missing))
            + "\n\nAvailable data-testid values:\n"
            + "\n".join(f"  - '{e}'" for e in sorted(existing))
        )
    return f"All {len(used)} data-testid locators match the HTML templates."


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



PLANNING_TOOLS = [read_requirements_file]
UNIT_TOOLS= [search_codebase, validate_python_syntax, validate_imports, check_test_structure, write_test_file]
INTEGRATION_TOOLS = [search_codebase, validate_python_syntax, validate_imports, check_test_structure, write_test_file]
E2E_TOOLS = [search_codebase, validate_python_syntax, validate_imports, check_test_structure, write_test_file, validate_selenium_locators]
