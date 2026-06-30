import os
from dotenv import load_dotenv
from core.state import QAuraState, E2ETestOutput
from core.tools import E2E_TOOLS
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
API_KEY = os.environ.get('E2E_TEST_API_KEY', '')
API_ENDPOINT = os.environ.get('E2E_TEST_ENDPOINT', '')
API_MODEL = os.environ.get('E2E_TEST_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura E2E Test Generator. Your job is to write \
end-to-end browser tests using Playwright (pytest-playwright) that exercise \
complete user journeys through the application under test.

You work on ANY application — do not assume a specific framework, set of pages,
URLs, or element names. Always discover the real structure of the app from the
codebase AND the live application before writing tests.

WORKFLOW:
1. You will receive the test plan with the components in e2e_scope.
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
4. Use the Playwright browser tools to explore the LIVE application:
   - Call `browser_navigate` to visit pages of the app.
   - Call `browser_snapshot` to capture the current DOM structure and discover
     real element selectors, roles, and text content.
   - Optionally call `browser_click`, `browser_type`, or `browser_fill_form`
     to test interactions and confirm they work before writing test code.
   This step is CRITICAL — it validates that the locators and flows you found
   in the codebase actually work in the running application.
5. Generate comprehensive E2E test files covering the real user flows of the app.

TEST WRITING RULES:
- Use `pytest-playwright` with the built-in `page` fixture.
- Locate elements using Playwright locators:
  - Prefer `page.get_by_test_id("...")` when elements have `data-testid` attributes.
  - Use `page.get_by_role(...)`, `page.get_by_text(...)`, or `page.get_by_label(...)`
    for semantic locators.
  - Fall back to `page.locator("css=...")` only when no semantic option exists.
- Use Playwright's built-in auto-waiting — do NOT use `time.sleep()`.
  For explicit waits, use `page.wait_for_selector(...)` or
  `expect(locator).to_be_visible()` from `playwright.sync_api`.
- Structure each test as a complete user journey: navigate → interact → assert.
- Use the `page` fixture directly — do NOT create manual browser/context setup.

BASE URL:
- Use the APP_BASE_URL environment variable:
  `BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:3000')`
- Never hard-code a host or port — always read from this variable.

WHAT TO COVER:
Derive the flows from the components in e2e_scope and what you find in the codebase
and the live app. For each component, test the primary success path plus the
meaningful failure paths the UI is supposed to handle (e.g. invalid input shows an
error, unauthenticated access is redirected). Typical journeys include
sign-in/sign-out, form submission and its confirmation, navigation between pages,
and any stateful action the UI performs — but only those that actually exist.

FILE NAMING:
- Name each test file as `test_e2e_<flow>.py` (e.g., `test_e2e_login.py`, `test_e2e_orders.py`).

VALIDATION (MANDATORY — do this before returning your final answer):
For EACH test file you generate, you MUST call these tools IN THIS ORDER:
1. validate_python_syntax     — fix any syntax errors, then re-run
2. validate_imports           — fix any broken imports, then re-run
3. check_test_structure       — ensure test_ functions exist with assertions
4. Use browser tools to verify — navigate to key pages and confirm the locators
   you used in your tests actually match elements on the live page
5. write_test_file            — persist to tests/ ONLY after 1-4 pass

If any validation step fails, FIX the code and re-validate. Never call
write_test_file with code that fails validation. Never return code you
have not validated and written to disk.

OUTPUT REQUIREMENTS:
- test_code: include the FULL source code — not a placeholder or reference.
- user_flows_covered: list each flow as a short description (e.g.,
  "User registration with valid input", "Login with invalid credentials shows error",
  "Browse products and place order").

{format_instructions}
"""

HUMAN_PROMPT = """Based on the test plan, please generate E2E tests for the following components:

{components}

Project summary: {project_summary}
Risk areas: {risk_areas}
"""

llm = ChatOpenAI(
    base_url=API_ENDPOINT,
    api_key=API_KEY,
    model=API_MODEL,
    temperature=0.2,
    timeout=300,
    max_retries=3,
)

parser = PydanticOutputParser(pydantic_object=E2ETestOutput)


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


async def e2e_gen_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node — generates E2E tests for e2e_scope using Playwright MCP."""
    print("--- Running E2E Test Generator ---")
    test_plan = state.get("test_plan")
    if not test_plan:
        return {"messages": ["No test plan found."]}

    e2e_components = [
        c for c in test_plan.components if c.name in test_plan.e2e_scope
    ]
    if not e2e_components:
        return {"messages": ["No e2e components found."]}

    components_text = "\n".join(
        f"- {c.name} (file: {c.file_path}, risk: {c.risk_level}): {c.description}"
        for c in e2e_components
    )

    callbacks = (config or {}).get("callbacks", [])
    system_msg = SYSTEM_PROMPT.format(format_instructions=parser.get_format_instructions())
    human_msg = HUMAN_PROMPT.format(
        components=components_text,
        project_summary=test_plan.project_summary,
        risk_areas=test_plan.risk_areas,
    )

    client = MultiServerMCPClient(get_mcp_config(playwright=True, leanctx=True))
    mcp_tools = await client.get_tools()
    all_tools = E2E_TOOLS + mcp_tools
    agent_subgraph = _build_agent_subgraph(all_tools)

    agent_result = await agent_subgraph.ainvoke(
        {"messages": [("system", system_msg), ("user", human_msg)]},
        config={"callbacks": callbacks},
    )

    try:
        output = robust_parse(agent_result["messages"][-1].content, E2ETestOutput, llm)
        tests = output.tests
    except Exception as e:
        print(f"Error parsing output: {e}")
        tests = []

    return {
        "e2e_tests": tests,
        "messages": [f"E2E Generator produced {len(tests)} test files."]
    }
