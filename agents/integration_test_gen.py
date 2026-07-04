import os
from dotenv import load_dotenv
from core.state import QAuraState, IntegrationTestOutput
from core.tools import INTEGRATION_TOOLS
from core.mcp_config import get_mcp_config
from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig

load_dotenv()
API_KEY = os.environ.get('INTEGRATION_TEST_API_KEY', '')
API_ENDPOINT = os.environ.get('INTEGRATION_TEST_ENDPOINT', '')
API_MODEL = os.environ.get('INTEGRATION_TEST_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Integration Test Generator.

Your job is to generate integration tests using **pytest** that validate the
interactions between modules — API endpoints, database state changes, and
cross-function data flow.

You work on ANY application — do not assume a specific web framework, database,
or module layout. Always discover the real structure from the codebase before
writing tests.

CRITICAL PATH RULE:
  Always use RELATIVE paths (e.g. `demo_app/server.py`, `src/auth.py`) when
  calling `ctx_read`, `ctx_search`, `ctx_tree`, or any file-access tool.
  NEVER construct or guess absolute paths like `C:/Users/.../project/file.py`.
  The tools resolve relative paths from the project root automatically.

MANDATORY WORKFLOW — you MUST follow these steps IN ORDER for EACH component.
Skipping any step is a failure. Do NOT return your final answer until every
component has been through ALL steps.

STEP 1 — UNDERSTAND PROJECT STRUCTURE
  Call `ctx_tree` on the project root (pass `.` or omit the path) to get a
  high-level view of the directory layout. Identify the web framework, database
  layer, and module boundaries.

STEP 2 — DISCOVER THE TECH STACK
  For each component, use these tools in order of preference:
  a) Call `ctx_read` with `mode=signatures` on the component's file to get
     function/class signatures — this reveals the API surface, decorators
     (route handlers, ORM models), and import paths.
  b) Call `ctx_search` to find route definitions (e.g. "@app.get", "@router.post",
     "@app.route"), database schema ("CREATE TABLE", model classes), and
     connection setup patterns.
  c) Call `ctx_read` with `mode=full` on specific files when you need complete
     implementation details (e.g. how the DB connection is managed, how the
     app instance is created).
  d) Use `search_codebase` for broad semantic queries when pattern search
     won't suffice (e.g. "database connection setup", "app factory").

  From this discovery, determine:
  - How to import and instantiate a test client for the web framework.
  - How to set up an isolated test database (in-memory preferred).
  - How to patch the DB connection so all code under test uses the test DB.

STEP 3 — GENERATE TESTS
  Write a complete pytest test file for the component following the rules below.

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

TEST WRITING RULES:

Framework & Style:
- Use `pytest` as the framework.
- These tests call REAL functions with a REAL test database.
- Do NOT mock the database — integration tests validate actual DB interactions.
- Descriptive names: `test_<endpoint_or_function>_<scenario>_<expected>`.
- Every test MUST have at least one `assert`.
- Use `@pytest.fixture` for reusable setup (DB, client).
- Use `@pytest.mark.parametrize` for multiple similar inputs.

What to test:
- The full call chain: API handler → business logic → database → response.
- Verify database state AFTER operations (query the DB to confirm writes).
- Test error propagation: bad input at the API level should return proper HTTP errors.
- Cross-module data flow: data written by one module is correctly read by another.

Database & Client Setup:
- Study the source code from Step 2 to determine:
  * How the app creates its DB connection (factory function, global, ORM session).
  * The correct patch target for the DB connection (patch at the call site).
  * How to initialize schema and seed data using the app's own functions.
- Prefer in-memory databases for speed when the DB engine supports it.
- Create a test client fixture that uses the patched DB connection.
- Example pattern (adapt to the actual framework and DB layer you discover):
  ```
  @pytest.fixture
  def test_db():
      conn = sqlite3.connect(":memory:")
      conn.row_factory = sqlite3.Row
      with patch('<module>.get_db', return_value=conn):
          init_db()
          seed_db()
          yield conn
      conn.close()
  ```

Import conventions:
- Study the source code from Step 2 to determine the correct import paths.
- Import the module under test using the path that matches the project structure.

File naming:
- `test_integration_<module>.py` — one test file per component.

{format_instructions}
"""

HUMAN_PROMPT = """Generate integration tests for the following components. For EACH one, you MUST:
1. Call ctx_tree to understand the project layout
2. Call ctx_read with mode=signatures to discover the API surface, framework, and DB layer
3. Call ctx_search or ctx_read mode=full to understand DB connection and route patterns
4. Write tests that exercise REAL cross-module interactions (no DB mocking)
5. Validate with validate_python_syntax, validate_imports, check_test_structure
6. Call write_test_file to save to disk
Do NOT return your final answer until every component has been written to disk.

Components to test:
{components}

Project summary: {project_summary}
Risk areas: {risk_areas}
"""

llm = ChatOpenAI(
    base_url=API_ENDPOINT,
    api_key=API_KEY,
    model=API_MODEL,
    temperature=0.2,
    timeout=180,
    max_retries=2,
)

parser = PydanticOutputParser(pydantic_object=IntegrationTestOutput)


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
    builder.add_node("tools", ToolNode(all_tools, handle_tool_errors=True))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()


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

    client = MultiServerMCPClient(get_mcp_config(leanctx=True))
    leanctx_tools = await client.get_tools()
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
