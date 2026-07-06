import os
from dotenv import load_dotenv
from core.tools import PLANNING_TOOLS
from core.state import QAuraState, TestPlan
from core.mcp_config import get_mcp_config
from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

load_dotenv()
API_KEY = os.environ.get('PLANNING_API_KEY', '')
API_ENDPOINT = os.environ.get('PLANNING_ENDPOINT', '')
API_MODEL = os.environ.get('PLANNING_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Test Architect.
Your job is to read the project requirements and produce a structured test plan that
downstream generators (Unit, Integration, E2E) will consume.

CRITICAL PATH RULE:
  Always use RELATIVE paths (e.g. `demo_app/server.py`, `src/auth.py`) when
  calling `ctx_read`, `ctx_search`, `ctx_tree`, or any file-access tool.
  NEVER construct or guess absolute paths like `C:/Users/.../project/file.py`.
  The tools resolve relative paths from the project root automatically.
  Component file_path values in the test plan MUST also be relative paths.

WORKFLOW:
1. Call `read_requirements_file` with the path provided by the user. Do NOT skip this step.
2. The requirements document specifies the directory containing the application under test.
   Call `ctx_tree` on that directory to discover the real directory layout and source files.
   Explore deeper into subdirectories as needed to find all models, views, URLs, templates,
   and static files.
3. Identify every testable component from the requirements document.
4. For EACH component, determine:
   - file_path: use a path confirmed by `ctx_tree`. If unsure whether a file
     contains the expected code, call `ctx_read` with `mode=signatures` to check.
   - testing_type: the PRIMARY test category (Unit, Integration, or E2E).
     * Unit — pure logic, calculations, validators, anything testable in isolation.
     * Integration — API routes, DB interactions, cross-module data flow.
     * E2E — browser-driven user journeys through the frontend.
   - risk_level:
     * High — involves auth, security, money, or you found bugs/vulnerabilities in the code.
     * Medium — complex logic or multiple dependencies.
     * Low — simple CRUD, static pages, trivial getters.
5. Populate the scope lists:
   - unit_scope: names of components whose testing_type is 'Unit'.
   - integration_scope: names of components whose testing_type is 'Integration'.
   - e2e_scope: names of components whose testing_type is 'E2E'.
   CRITICAL: every name in unit_scope / integration_scope / e2e_scope MUST exactly
   match a `name` field in the components list. No mismatches allowed.
6. List risk_areas — identify risks by reading the actual source code. Look for security
   issues, bugs, missing validation, hardcoded values, or any code that could break.
QUALITY RULES:
- Aim for 5-10 components. Too few = gaps in coverage; too many = redundant splitting.
- Each component should map to at most one source file. If a file has multiple concerns
  (e.g., auth + session), split into separate components.
- The project_summary should be 1-2 sentences capturing what the app does.

REVISION INSTRUCTIONS:
If you receive human feedback indicating that a previous plan was rejected, you MUST address the feedback in your new plan. You may skip re-reading the requirements file if you already know the context, and focus on adjusting the components or scopes as requested by the user.

{format_instructions}
"""

HUMAN_PROMPT = """Analyze the requirements located at: {path} and create a comprehensive test plan."""

llm = ChatOpenAI(
    base_url=API_ENDPOINT,
    api_key=API_KEY,
    model=API_MODEL,
    temperature=0,
    timeout=180,
    max_retries=2,
)

parser = PydanticOutputParser(pydantic_object=TestPlan)


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

    client = MultiServerMCPClient(get_mcp_config(leanctx=True))
    leanctx_tools = await client.get_tools()
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


def hitl_approval_node(state: QAuraState) -> dict:
    """Pauses execution for human review."""
    print("--- HITL Gate: Awaiting Approval ---")

    test_plan = state.get("test_plan")
    human_response = interrupt({
        "message": "Please review the test plan.",
    })

    approved = human_response.get("approved", False)
    feedback = human_response.get("feedback", "")

    messages = [f"Human approval status: {approved}"]
    if not approved and feedback:
        messages.append(("user", f"Feedback on previous plan: {feedback}. Please revise."))

    return {
        "plan_approved": approved,
        "messages": messages
    }
