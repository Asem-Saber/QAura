import os
from dotenv import load_dotenv
from core.state import QAuraState, UnitTestOutput
from core.tools import UNIT_TOOLS
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
API_KEY = os.environ.get('UNIT_TEST_API_KEY', '')
API_ENDPOINT = os.environ.get('UNIT_TEST_ENDPOINT', '')
API_MODEL = os.environ.get('UNIT_TEST_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Unit Test Generator.

Your job is to generate isolated, mock-heavy unit tests using **pytest** for the
components listed in the test plan.

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
  high-level view of the directory layout. This helps you understand module
  boundaries and import paths.

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

HUMAN_PROMPT = """Generate unit tests for the following components. For EACH one, you MUST:
1. Call ctx_tree to understand the project layout
2. Call ctx_read with mode=signatures to get the API surface
3. Write tests based on the real implementation
4. Validate with validate_python_syntax, validate_imports, check_test_structure
5. Call write_test_file to save to disk
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

parser = PydanticOutputParser(pydantic_object=UnitTestOutput)


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

    client = MultiServerMCPClient(get_mcp_config(leanctx=True))
    leanctx_tools = await client.get_tools()
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
