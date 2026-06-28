# lean-ctx MCP Integration for QAura Agents

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give QAura's LLM agents access to lean-ctx's context-compressed code reading and search tools at runtime, reducing token consumption and improving code understanding accuracy across all agents — including the planning agent, test generators, and healing agents.

**Architecture:** Extend the existing MCP integration pattern (currently Playwright-only) to support multiple MCP servers per agent. A new `core/mcp_config.py` replaces `core/playwright_mcp.py` with a unified config builder. Agents that need browser automation get Playwright + lean-ctx; agents that only need code analysis get lean-ctx alone. The three currently-synchronous agents (planning_agent, unit_test_gen, integration_test_gen) are converted to the async MCP pattern.

**Tech Stack:** lean-ctx (Rust binary, MCP stdio), langchain-mcp-adapters, LangGraph async nodes

## Global Constraints

- lean-ctx binary must be installed and on PATH (verified via `lean-ctx --version`)
- `langchain-mcp-adapters` is already a project dependency
- All agent node functions that use MCP must be `async def`
- Existing `search_codebase` (ChromaDB) stays available alongside lean-ctx tools — agents choose the best tool per query
- `LEAN_CTX_DISABLED` env var disables lean-ctx when set to `1` (graceful degradation)

---

### Task 1: Create `core/mcp_config.py` — unified MCP server config

**Files:**
- Create: `core/mcp_config.py`
- Delete: `core/playwright_mcp.py` (after all imports are migrated)
- Test: `tests/test_mcp_config.py`

**Interfaces:**
- Produces: `get_mcp_config(playwright: bool = False, leanctx: bool = True) -> dict` — returns a MultiServerMCPClient-compatible config dict containing the requested MCP servers

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_config.py
import os
import pytest
from unittest.mock import patch


def test_leanctx_only_config():
    from core.mcp_config import get_mcp_config

    config = get_mcp_config(playwright=False, leanctx=True)
    assert "lean-ctx" in config
    assert "playwright" not in config
    assert config["lean-ctx"]["transport"] == "stdio"
    assert config["lean-ctx"]["command"] == "lean-ctx"


def test_playwright_only_config():
    from core.mcp_config import get_mcp_config

    config = get_mcp_config(playwright=True, leanctx=False)
    assert "playwright" in config
    assert "lean-ctx" not in config


def test_full_config():
    from core.mcp_config import get_mcp_config

    config = get_mcp_config(playwright=True, leanctx=True)
    assert "playwright" in config
    assert "lean-ctx" in config


def test_playwright_headless_env():
    from core.mcp_config import get_mcp_config

    with patch.dict(os.environ, {"PLAYWRIGHT_HEADLESS": "false"}):
        config = get_mcp_config(playwright=True, leanctx=False)
        assert "--headless" not in config["playwright"]["args"]

    with patch.dict(os.environ, {"PLAYWRIGHT_HEADLESS": "true"}):
        config = get_mcp_config(playwright=True, leanctx=False)
        assert "--headless" in config["playwright"]["args"]


def test_leanctx_disabled_env():
    from core.mcp_config import get_mcp_config

    with patch.dict(os.environ, {"LEAN_CTX_DISABLED": "1"}):
        config = get_mcp_config(playwright=False, leanctx=True)
        assert "lean-ctx" not in config


def test_empty_config_raises():
    from core.mcp_config import get_mcp_config

    config = get_mcp_config(playwright=False, leanctx=False)
    assert config == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mcp_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.mcp_config'`

- [ ] **Step 3: Implement `core/mcp_config.py`**

```python
# core/mcp_config.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_mcp_config.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/mcp_config.py tests/test_mcp_config.py
git commit -m "feat: add unified MCP config supporting lean-ctx + Playwright"
```

---

### Task 2: Convert `agents/unit_test_gen.py` to async with lean-ctx MCP

**Files:**
- Modify: `agents/unit_test_gen.py`

**Interfaces:**
- Consumes: `get_mcp_config(leanctx=True)` from `core.mcp_config`
- Produces: `async def unit_test_gen_node(state, config)` (was sync `def`)

- [ ] **Step 1: Update imports**

Replace the current imports block:

```python
# OLD
from core.tools import UNIT_TOOLS

# NEW
from core.tools import UNIT_TOOLS
from core.mcp_config import get_mcp_config
from langchain_mcp_adapters.client import MultiServerMCPClient
```

- [ ] **Step 2: Extract `_build_agent_subgraph` helper and remove module-level subgraph**

Delete these module-level declarations (lines 103–118):

```python
llm_with_tools = llm.bind_tools(UNIT_TOOLS)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

def call_model(state: AgentState):
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", ToolNode(UNIT_TOOLS))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
agent_subgraph = builder.compile()
```

Replace with the pattern already used by e2e/defect/self-healing agents:

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def _build_agent_subgraph(all_tools):
    """Build the ReAct agent subgraph with the given tools."""
    llm_with_tools = llm.bind_tools(all_tools)

    def call_model(state: AgentState):
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(all_tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()
```

- [ ] **Step 3: Make `unit_test_gen_node` async with MCP client**

Replace the node function:

```python
async def unit_test_gen_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node — generates unit tests for components in unit_scope."""
    print("--- Running Unit Test Generator ---")
    test_plan = state.get("test_plan")
    if not test_plan:
        return {"messages": ["No test plan found."]}

    unit_components = [
        c for c in test_plan.components if c.name in test_plan.unit_scope
    ]
    if not unit_components:
        return {"messages": ["No unit components found."]}

    components_text = "\n".join(
        f"- {c.name} (file: {c.file_path}, risk: {c.risk_level}): {c.description}"
        for c in unit_components
    )

    callbacks = (config or {}).get("callbacks", [])
    system_msg = SYSTEM_PROMPT.format(format_instructions=parser.get_format_instructions())
    human_msg = HUMAN_PROMPT.format(
        components=components_text,
        project_summary=test_plan.project_summary,
        risk_areas=test_plan.risk_areas,
    )

    client = MultiServerMCPClient(get_mcp_config(leanctx=True)) as client:
        leanctx_tools = client.get_tools()
        all_tools = UNIT_TOOLS + leanctx_tools
        agent_subgraph = _build_agent_subgraph(all_tools)

        agent_result = await agent_subgraph.ainvoke(
            {"messages": [("system", system_msg), ("user", human_msg)]},
            config={"callbacks": callbacks},
        )

    try:
        output = robust_parse(agent_result["messages"][-1].content, UnitTestOutput, llm)
        tests = output.tests
    except Exception as e:
        print(f"Error parsing output: {e}")
        tests = []

    return {
        "unit_tests": tests,
        "messages": [f"Unit Test Generator produced {len(tests)} test files."]
    }
```

- [ ] **Step 4: Update SYSTEM_PROMPT with lean-ctx tool guidance**

Add to the SYSTEM_PROMPT after the existing `STEP 1 — RETRIEVE SOURCE CODE` section, replacing it with enhanced instructions:

```python
SYSTEM_PROMPT = """You are the QAura Unit Test Generator.

Your job is to generate isolated, mock-heavy unit tests using **pytest** for the
components listed in the test plan.

MANDATORY WORKFLOW — you MUST follow these steps IN ORDER for EACH component.
Skipping any step is a failure. Do NOT return your final answer until every
component has been through ALL steps.

STEP 1 — UNDERSTAND PROJECT STRUCTURE
  Call `ctx_tree` on the project root to get a high-level view of the directory
  layout. This helps you understand module boundaries and import paths.

STEP 2 — RETRIEVE SOURCE CODE
  For each component, use these tools in order of preference:
  a) Call `ctx_read` with `mode=signatures` on the component's file to get
     function/class signatures without full implementation — this is cheaper
     and gives you the API surface you need for writing tests.
  b) If you need to understand internal logic (e.g. to test edge cases), call
     `ctx_read` with `mode=full` on specific files.
  c) Use `ctx_search` to find specific patterns across the codebase (e.g.
     import paths, decorator usage, config values).
  d) Use `search_codebase` for broad semantic queries when you need to find
     related code by concept (e.g. "authentication middleware").

STEP 3 — GENERATE TESTS
  Write a complete pytest test file for the component (rules below).

STEP 4 — VALIDATE (loop until clean)
  Call these tools in order. If ANY fails, fix the code and re-run from 4a:
    4a. `validate_python_syntax`  → fix syntax errors
    4b. `validate_imports`        → fix broken imports
    4c. `check_test_structure`    → ensure test_ functions with assertions

STEP 5 — WRITE TO DISK
  Call `write_test_file` with the validated code. This is NON-OPTIONAL.
  You have NOT completed a component until write_test_file succeeds.
  Do NOT move to the next component until the current one is written.

STEP 6 — FINAL OUTPUT
  Only after ALL components are validated and written, return your structured
  output. The `test_code` field must contain the FULL source code you wrote —
  not a placeholder or summary.

TEST WRITING RULES

Framework & Style:
- Use `pytest` with `unittest.mock` (Mock, patch, MagicMock).
- Descriptive names: `test_<function>_<scenario>_<expected>`.
- Every test MUST have at least one `assert`.
- Use `@pytest.fixture` for reusable setup.
- Use `@pytest.mark.parametrize` for multiple similar inputs.

Isolation:
- Mock ALL external dependencies: databases, file I/O, network calls, third-party services.
- Patch at the call site (where the dependency is looked up in the module under test).
- Never connect to real infrastructure in a unit test.

Coverage per function:
- Happy path (valid inputs → expected output)
- Edge cases (empty inputs, zero, None, boundary values)
- Error paths (invalid input → expected exception or error return)

Import conventions:
- Study the source code retrieved in Step 2 to determine the correct import paths.
- Import the module under test using the path that matches the project structure.

File naming:
- `test_<module>.py` — one test file per component.

{format_instructions}
"""
```

- [ ] **Step 5: Verify import works**

Run: `python -c "from agents.unit_test_gen import unit_test_gen_node; print(type(unit_test_gen_node))"`
Expected: `<class 'function'>` (async function)

- [ ] **Step 6: Commit**

```bash
git add agents/unit_test_gen.py
git commit -m "feat: convert unit_test_gen to async with lean-ctx MCP tools"
```

---

### Task 3: Convert `agents/integration_test_gen.py` to async with lean-ctx MCP

**Files:**
- Modify: `agents/integration_test_gen.py`

**Interfaces:**
- Consumes: `get_mcp_config(leanctx=True)` from `core.mcp_config`
- Produces: `async def integration_gen_node(state, config)` (was sync `def`)

- [ ] **Step 1: Update imports**

Add to the existing imports:

```python
from core.mcp_config import get_mcp_config
from langchain_mcp_adapters.client import MultiServerMCPClient
```

- [ ] **Step 2: Replace module-level subgraph with `_build_agent_subgraph` helper**

Delete the module-level declarations (lines 114–129):

```python
llm_with_tools = llm.bind_tools(INTEGRATION_TOOLS)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

def call_model(state: AgentState):
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", ToolNode(INTEGRATION_TOOLS))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
agent_subgraph = builder.compile()
```

Replace with:

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def _build_agent_subgraph(all_tools):
    """Build the ReAct agent subgraph with the given tools."""
    llm_with_tools = llm.bind_tools(all_tools)

    def call_model(state: AgentState):
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(all_tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()
```

- [ ] **Step 3: Make `integration_gen_node` async with MCP client**

Replace the node function:

```python
async def integration_gen_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node — generates integration tests for components in integration_scope."""
    print("--- Running Integration Test Generator ---")
    test_plan = state.get("test_plan")
    if not test_plan:
        return {"messages": ["No test plan found."]}

    integration_components = [
        c for c in test_plan.components if c.name in test_plan.integration_scope
    ]
    if not integration_components:
        return {"messages": ["No integration components found."]}

    components_text = "\n".join(
        f"- {c.name} (file: {c.file_path}, risk: {c.risk_level}): {c.description}"
        for c in integration_components
    )

    callbacks = (config or {}).get("callbacks", [])
    system_msg = SYSTEM_PROMPT.format(format_instructions=parser.get_format_instructions())
    human_msg = HUMAN_PROMPT.format(
        components=components_text,
        project_summary=test_plan.project_summary,
        risk_areas=test_plan.risk_areas,
    )

    client = MultiServerMCPClient(get_mcp_config(leanctx=True)) as client:
        leanctx_tools = client.get_tools()
        all_tools = INTEGRATION_TOOLS + leanctx_tools
        agent_subgraph = _build_agent_subgraph(all_tools)

        agent_result = await agent_subgraph.ainvoke(
            {"messages": [("system", system_msg), ("user", human_msg)]},
            config={"callbacks": callbacks},
        )

    try:
        output = robust_parse(agent_result["messages"][-1].content, IntegrationTestOutput, llm)
        tests = output.tests
        contracts = output.api_contracts_tested
    except Exception as e:
        print(f"Error parsing output: {e}")
        tests = []
        contracts = []

    return {
        "integration_tests": tests,
        "messages": [
            f"Integration Generator produced {len(tests)} test files. "
            f"API contracts tested: {', '.join(contracts) if contracts else 'None'}"
        ]
    }
```

- [ ] **Step 4: Update SYSTEM_PROMPT with lean-ctx tool guidance**

Replace the WORKFLOW section (lines 28–34) of the existing SYSTEM_PROMPT:

```python
SYSTEM_PROMPT = """You are the QAura Integration Test Generator.

Your job is to generate integration tests using **pytest** that validate the
interactions between modules — API endpoints, database state changes, and
cross-function data flow.

WORKFLOW:
1. You will receive the test plan with components in integration_scope.
2. Start by calling `ctx_tree` on the project root to understand the directory layout.
3. For EACH component, use these tools to retrieve code:
   a) Call `ctx_read` with `mode=signatures` on the component file to get the API surface.
   b) Call `ctx_search` to find route handlers (search for "@app.get", "@app.post", etc.).
   c) Call `ctx_search` to find database schema (search for "CREATE TABLE" or model definitions).
   d) Call `ctx_read` with `mode=full` on specific files when you need complete implementation details.
   e) Use `search_codebase` for broad semantic queries (e.g. "database connection setup").
4. Generate comprehensive integration test files.

TEST WRITING RULES:
- Use `pytest` as the framework.
- These tests call REAL functions with a REAL test database.
- Do NOT mock the database — integration tests validate actual DB interactions.
- Test the full call chain: API handler → business logic → database → response.
- Verify database state AFTER operations (query the DB to confirm writes).
- Test error propagation: bad input at the API level should return proper HTTP errors.

DATABASE SETUP:
- Use an in-memory SQLite database for speed: `sqlite3.connect(":memory:")`.
- In a `@pytest.fixture`, call `init_db()` and `seed_db()` from the models module
  to create the schema and populate test data. Teardown by closing the connection.
- Patch `models.get_db` to return your test connection so all code under test uses it.
- Example pattern:
  ```
  @pytest.fixture
  def test_db():
      conn = sqlite3.connect(":memory:")
      conn.row_factory = sqlite3.Row
      with patch('models.get_db', return_value=conn):
          init_db()
          seed_db()
          yield conn
      conn.close()
  ```

API TEST SETUP:
- Import the FastAPI app: `from server import app`
- Use `from fastapi.testclient import TestClient` → `client = TestClient(app)`
- Combine with the database fixture so API calls hit the test DB.
- Example:
  ```
  @pytest.fixture
  def client(test_db):
      with patch('models.get_db', return_value=test_db):
          yield TestClient(app)
  ```

IMPORT CONVENTIONS:
- Import modules by their bare name: `from server import app`, `from models import init_db, seed_db`.
  The test runner's conftest.py handles path resolution.

FILE NAMING:
- Name each test file as `test_integration_<module>.py` (e.g., `test_integration_server.py`).

VALIDATION (MANDATORY — do this before returning your final answer):
For EACH test file you generate, you MUST call these tools IN THIS ORDER:
1. validate_python_syntax  — fix any syntax errors, then re-run
2. validate_imports        — fix any broken imports, then re-run
3. check_test_structure    — ensure test_ functions exist with assertions
4. write_test_file         — persist the file to tests/ ONLY after 1-3 pass

If any validation step fails, FIX the code and re-validate. Never call
write_test_file with code that fails validation. Never return code you
have not validated and written to disk.

OUTPUT REQUIREMENTS:
- test_code: include the FULL source code — not a placeholder or reference.
- api_contracts_tested: list each endpoint as "METHOD /path" (e.g., "POST /register", "GET /products").
- db_fixtures_needed: list the tables or seed data required (e.g., "users table with test user",
  "products table with 3 sample products").

{format_instructions}
"""
```

- [ ] **Step 5: Verify import works**

Run: `python -c "from agents.integration_test_gen import integration_gen_node; print(type(integration_gen_node))"`
Expected: `<class 'function'>` (async function)

- [ ] **Step 6: Commit**

```bash
git add agents/integration_test_gen.py
git commit -m "feat: convert integration_test_gen to async with lean-ctx MCP tools"
```

---

### Task 4: Convert `agents/planning_agent.py` to async with lean-ctx MCP

**Files:**
- Modify: `agents/planning_agent.py`

**Interfaces:**
- Consumes: `get_mcp_config(leanctx=True)` from `core.mcp_config`
- Produces: `async def test_architect_node(state, config)` (was sync `def`). `hitl_approval_node` stays sync (no tools needed).

- [ ] **Step 1: Update imports**

Add to the existing imports:

```python
from core.mcp_config import get_mcp_config
from langchain_mcp_adapters.client import MultiServerMCPClient
```

- [ ] **Step 2: Replace module-level subgraph with `_build_agent_subgraph` helper**

Delete the module-level declarations (lines 67–82):

```python
llm_with_tools = llm.bind_tools(PLANNING_TOOLS)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

def call_model(state: AgentState):
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", ToolNode(PLANNING_TOOLS))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
agent_subgraph = builder.compile()
```

Replace with:

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def _build_agent_subgraph(all_tools):
    """Build the ReAct agent subgraph with the given tools."""
    llm_with_tools = llm.bind_tools(all_tools)

    def call_model(state: AgentState):
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(all_tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()
```

- [ ] **Step 3: Make `test_architect_node` async with MCP client**

Replace the node function:

```python
async def test_architect_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node for Phase 1."""
    print("--- Running Test Architect ---")
    callbacks = (config or {}).get("callbacks", [])

    system_msg = SYSTEM_PROMPT.format(format_instructions=parser.get_format_instructions())
    human_msg = HUMAN_PROMPT.format(path=state["requirements_path"])

    invoke_msgs = [("system", system_msg), ("user", human_msg)]

    if state.get("test_plan"):
        plan_json = state["test_plan"].model_dump_json(indent=2)
        invoke_msgs.append(("ai", f"Here is my proposed plan:\n{plan_json}"))

    feedback_msgs = [m for m in state.get("messages", []) if isinstance(m, tuple) and m[0] == "user"]
    invoke_msgs.extend(feedback_msgs)

    client = MultiServerMCPClient(get_mcp_config(leanctx=True)) as client:
        leanctx_tools = client.get_tools()
        all_tools = PLANNING_TOOLS + leanctx_tools
        agent_subgraph = _build_agent_subgraph(all_tools)

        agent_result = await agent_subgraph.ainvoke(
            {"messages": invoke_msgs},
            config={"callbacks": callbacks},
        )

    final_output = agent_result["messages"][-1].content

    try:
        generated_plan = robust_parse(final_output, TestPlan, llm)
        num_components = len(generated_plan.components)
    except Exception as e:
        print(f"Error parsing JSON: {e}\nAgent Output was: {final_output[:500]}")
        generated_plan = None
        num_components = 0

    return {
        "test_plan": generated_plan,
        "messages": [f"Architect generated a test plan with {num_components} components."]
    }
```

Note: `hitl_approval_node` remains sync — it uses `interrupt()` and no tools.

- [ ] **Step 4: Update SYSTEM_PROMPT with lean-ctx tool guidance**

Add a new step between the existing step 1 (read requirements) and step 2 (identify components). Insert after `1. Call \`read_requirements_file\`...`:

```
1b. Call `ctx_tree` on the project root to discover the ACTUAL directory layout
    and source files. Cross-reference this with the requirements document's
    'Source Files Under Test' section. If the requirements list a file that
    does not exist, or if there are source files not mentioned in the
    requirements, note the discrepancy and use the real file paths in your plan.
    This ensures `file_path` values in each TestComponent are accurate.
```

Also update step 3 to add `ctx_read` as an option:

```
3. For EACH component, determine:
   - file_path: verify the path exists using the `ctx_tree` output. If unsure,
     call `ctx_read` with `mode=signatures` on the candidate file to confirm
     it contains the expected functions/classes.
   - testing_type: ...
```

The full updated WORKFLOW section becomes:

```
WORKFLOW:
1. Call `read_requirements_file` with the path provided by the user. Do NOT skip this step.
2. Call `ctx_tree` on the project root to discover the real directory layout and
   source files. Cross-reference this with the requirements document's
   'Source Files Under Test' section. If the requirements list a file path that
   does not exist on disk, or if source files exist that are not mentioned,
   note the discrepancy and use the real file paths in your plan.
3. Identify every testable component from the requirements document.
4. For EACH component, determine:
   - file_path: use a path confirmed by `ctx_tree`. If unsure whether a file
     contains the expected code, call `ctx_read` with `mode=signatures` to check.
   - testing_type: the PRIMARY test category (Unit, Integration, or E2E).
     * Unit — pure logic, calculations, validators, anything testable in isolation.
     * Integration — API routes, DB interactions, cross-module data flow.
     * E2E — browser-driven user journeys through the frontend.
   - risk_level:
     * High — explicitly listed in 'Known Risk Areas' or involves auth/security/money.
     * Medium — complex logic or multiple dependencies but not a known risk.
     * Low — simple CRUD, static pages, trivial getters.
5. Populate the scope lists:
   - unit_scope: names of components whose testing_type is 'Unit'.
   - integration_scope: names of components whose testing_type is 'Integration'.
   - e2e_scope: names of components whose testing_type is 'E2E'.
   CRITICAL: every name in unit_scope / integration_scope / e2e_scope MUST exactly
   match a `name` field in the components list. No mismatches allowed.
6. List risk_areas — extract directly from the 'Known Risk Areas' section of the requirements.
```

- [ ] **Step 5: Verify import works**

Run: `python -c "from agents.planning_agent import test_architect_node, hitl_approval_node; print('planning OK')"`
Expected: `planning OK`

- [ ] **Step 6: Commit**

```bash
git add agents/planning_agent.py
git commit -m "feat: convert planning_agent to async with lean-ctx for project structure discovery"
```

---

### Task 5: Add lean-ctx to Playwright-enabled agents

**Files:**
- Modify: `agents/e2e_test_gen.py` (import change + config call + prompt update)
- Modify: `agents/defect_intelligence_agent.py` (import change + config call + prompt update)
- Modify: `agents/self_healing_agent.py` (import change + config call + prompt update)

**Interfaces:**
- Consumes: `get_mcp_config(playwright=True, leanctx=True)` from `core.mcp_config`
- Produces: Same async node signatures, now with lean-ctx tools added to tool list

All three agents follow the same change pattern. Apply to each:

- [ ] **Step 1: Update import in all three agents**

In each file, replace:
```python
from core.playwright_mcp import get_mcp_config
```
With:
```python
from core.mcp_config import get_mcp_config
```

- [ ] **Step 2: Update MCP config call in all three agents**

In each file, replace:
```python
client = MultiServerMCPClient(get_mcp_config()) as client:
```
With:
```python
client = MultiServerMCPClient(get_mcp_config(playwright=True, leanctx=True)) as client:
```

- [ ] **Step 3: Update `agents/e2e_test_gen.py` SYSTEM_PROMPT**

In the WORKFLOW section, add a new step 2 and renumber. Insert after step 1 ("receive the test plan"):

Add between the existing step 2 (search_codebase) and step 3 (browser tools):

```
2. Use lean-ctx tools to efficiently understand the codebase structure:
   - Call `ctx_tree` on the project root to map the directory layout.
   - Call `ctx_read` with `mode=signatures` on component source files to get
     function/class signatures without loading full implementations.
   - Call `ctx_search` to find specific patterns (route definitions, template
     references, form element names) across the codebase.
   - Use `search_codebase` for broad semantic queries when pattern search
     won't suffice.
3. Use `ctx_read` with `mode=full` only when you need detailed implementation
   to understand page behavior or form submission logic.
```

Renumber existing "Use the Playwright browser tools" from step 3 to step 4, and "Generate comprehensive E2E test files" from step 4 to step 5.

- [ ] **Step 4: Update `agents/defect_intelligence_agent.py` SYSTEM_PROMPT**

In the investigation steps, add lean-ctx guidance. Replace step 2:

```
2. Call `ctx_read` with `mode=signatures` on the component file to understand the
   module's API surface. Then call `ctx_read` with `mode=full` to get the complete
   implementation. Use `ctx_search` to find related code (callers, config values).
   Fall back to `search_codebase` for broad semantic queries.
```

Replace step 3:

```
3. Call `ctx_read` with `mode=full` on the failing test file to read it with
   context compression, understanding what it asserts. (Alternative: call
   `read_test_file` if ctx_read is unavailable.)
```

- [ ] **Step 5: Update `agents/self_healing_agent.py` SYSTEM_PROMPT**

In the SELF_HEAL_LOCATOR section, update step 2:

```
2. Call `ctx_read` with `mode=signatures` on the component file to understand
   the current API surface. Then use `ctx_search` to find the correct import
   paths, function signatures, and URLs. Fall back to `search_codebase` for
   broad semantic queries.
```

In the SELF_HEAL_LOGIC section, update step 1:

```
1. Call `ctx_read` with `mode=full` on the affected component's file path to
   get the complete implementation with context compression.
```

- [ ] **Step 6: Verify all imports work**

Run:
```bash
python -c "from agents.e2e_test_gen import e2e_gen_node; print('e2e OK')"
python -c "from agents.defect_intelligence_agent import defect_intelligence_agent_node; print('defect OK')"
python -c "from agents.self_healing_agent import self_healing_agent_node; print('heal OK')"
```
Expected: All three print OK

- [ ] **Step 7: Delete `core/playwright_mcp.py`**

```bash
git rm core/playwright_mcp.py
```

Verify no remaining imports reference it:
```bash
grep -r "from core.playwright_mcp" agents/ core/
```
Expected: No matches

- [ ] **Step 8: Commit**

```bash
git add agents/e2e_test_gen.py agents/defect_intelligence_agent.py agents/self_healing_agent.py
git add -u core/playwright_mcp.py
git commit -m "feat: add lean-ctx MCP to e2e, defect, and self-healing agents"
```

---

### Task 6: Update `core/graph.py` for fully async pipeline

**Files:**
- Modify: `core/graph.py`

**Interfaces:**
- Consumes: `async def test_architect_node(...)` (Task 4), `async def unit_test_gen_node(...)` (Task 2), `async def integration_gen_node(...)` (Task 3)
- Produces: No interface change — `run_pipeline_phase1` and `run_pipeline_phase2` are already async

- [ ] **Step 1: Verify — no code change needed**

`core/graph.py` already uses `graph.astream()` and `asyncio.run(main())`. LangGraph handles async node functions natively — if a node is `async def`, LangGraph awaits it automatically.

Verify by running:

```bash
python -c "
import asyncio
from core.graph import graph
print('Graph nodes:', list(graph.nodes.keys()))
print('Graph compiled successfully')
"
```

Expected: Prints the node list and "Graph compiled successfully" without errors.

- [ ] **Step 2: Commit (only if changes were needed)**

If verification passes with no changes, skip this step. If there were import issues or wiring changes needed, commit them:

```bash
git add core/graph.py
git commit -m "fix: ensure graph handles async unit/integration nodes"
```

---

### Task 7: Verification and cleanup

**Files:**
- Modify: `requirements.txt` (add lean-ctx note)
- Modify: `.env` (add LEAN_CTX_DISABLED option)

- [ ] **Step 1: Run the config unit tests**

```bash
python -m pytest tests/test_mcp_config.py -v
```

Expected: All tests PASS

- [ ] **Step 2: Run import smoke test for all agents**

```bash
python -c "
from core.mcp_config import get_mcp_config
from agents.planning_agent import test_architect_node, hitl_approval_node
from agents.unit_test_gen import unit_test_gen_node
from agents.integration_test_gen import integration_gen_node
from agents.e2e_test_gen import e2e_gen_node
from agents.defect_intelligence_agent import defect_intelligence_agent_node
from agents.self_healing_agent import self_healing_agent_node
from core.graph import graph

print('All imports OK')
print('MCP config (leanctx only):', list(get_mcp_config(leanctx=True).keys()))
print('MCP config (full):', list(get_mcp_config(playwright=True, leanctx=True).keys()))
print('Graph nodes:', list(graph.nodes.keys()))
"
```

Expected:
```
All imports OK
MCP config (leanctx only): ['lean-ctx']
MCP config (full): ['lean-ctx', 'playwright']
Graph nodes: ['test_architect', 'human_approval', 'unit_test_gen', 'e2e_gen', 'execution_agent', 'reporting_agent', 'defect_intelligence_agent', 'self_healing_agent']
```

- [ ] **Step 3: Verify lean-ctx MCP server starts**

```bash
python -c "
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from core.mcp_config import get_mcp_config

async def check():
    client = MultiServerMCPClient(get_mcp_config(leanctx=True)) as client:
        tools = client.get_tools()
        tool_names = [t.name for t in tools]
        print(f'lean-ctx loaded {len(tools)} tools')
        # Verify key tools are present
        for expected in ['ctx_read', 'ctx_search', 'ctx_tree']:
            found = any(expected in name for name in tool_names)
            print(f'  {expected}: {\"found\" if found else \"MISSING\"}')

asyncio.run(check())
"
```

Expected: lean-ctx loads its tools and ctx_read, ctx_search, ctx_tree are present

- [ ] **Step 4: Add documentation comment to `.env`**

Add to `.env` above PLAYWRIGHT_HEADLESS:

```
# lean-ctx context compression (set to 1 to disable)
# LEAN_CTX_DISABLED=1
```

- [ ] **Step 5: Pipeline smoke test (manual)**

1. Start the demo app server: `python demo_app/server.py`
2. Run the QAura pipeline: `python core/graph.py`
3. Verify in stream output that agents call lean-ctx tools:
   - `[test_architect] Agent calling tools: [read_requirements_file, ctx_tree, ...]`
   - `[unit_test_gen] Agent calling tools: [ctx_tree, ...]`
   - `[unit_test_gen] Agent calling tools: [ctx_read, ...]`
4. Verify generated test files still work: `python -m pytest tests/ -v`

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete lean-ctx integration across all QAura agents"
```

---

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `core/mcp_config.py` | **Create** | Unified MCP config builder (Playwright + lean-ctx) |
| `core/playwright_mcp.py` | **Delete** | Replaced by `core/mcp_config.py` |
| `tests/test_mcp_config.py` | **Create** | Unit tests for MCP config |
| `agents/planning_agent.py` | **Modify** | Async node, lean-ctx MCP, `ctx_tree` for project structure discovery |
| `agents/unit_test_gen.py` | **Modify** | Async node, lean-ctx MCP, updated prompt |
| `agents/integration_test_gen.py` | **Modify** | Async node, lean-ctx MCP, updated prompt |
| `agents/e2e_test_gen.py` | **Modify** | Import → mcp_config, add lean-ctx to config, updated prompt |
| `agents/defect_intelligence_agent.py` | **Modify** | Import → mcp_config, add lean-ctx to config, updated prompt |
| `agents/self_healing_agent.py` | **Modify** | Import → mcp_config, add lean-ctx to config, updated prompt |
| `core/graph.py` | **Verify** | Should need no changes (async nodes handled natively) |
