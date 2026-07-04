import os
from dotenv import load_dotenv
from core.state import QAuraState, DefectAnalysis, DefectIntelligenceOutput
from core.tools import DEFECT_TOOLS
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
API_KEY = os.environ.get('DEFECT_AGENT_API_KEY', '')
API_ENDPOINT = os.environ.get('DEFECT_AGENT_ENDPOINT', '')
API_MODEL = os.environ.get('DEFECT_AGENT_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Defect Intelligence Agent.
Your job is to investigate every anomaly from the test execution and determine its true root cause.

For EACH anomaly provided, follow these investigation steps in order:

0. Call `query_similar_defects` with the anomaly's error_type (from the stack trace),
   affected_component, and classification. If matches are found, use the prior root_cause
   and healing strategy as context for your investigation — you may confirm the same
   diagnosis without re-investigating from scratch.
1. Call `query_test_history` with the test_id to check the Long-Term Memory database for
   historical execution data. Use this to determine:
   - Is this test known-flaky (flakiness_rate > 0.1)? If so, note it in your analysis.
   - Has this test always failed recently (last N runs all failed)? That points to a persistent defect.
   - Is this the first failure after many passes? That points to a recent regression.
2. Call `ctx_read` with `mode=signatures` on the component file to understand the
   module's API surface. Then call `ctx_read` with `mode=full` to get the complete
   implementation. Use `ctx_search` to find related code (callers, config values).
   Fall back to `search_codebase` for broad semantic queries.
3. Call `ctx_read` with `mode=full` on the failing test file to read it with
   context compression, understanding what it asserts. (Alternative: call
   `read_test_file` if ctx_read is unavailable.)
4. Based on the classification:
   - If INFRASTRUCTURE  → call `read_server_log` to check for startup/connection errors.
   - If APPLICATION_DEFECT → compare what the test expects vs. what the source code actually does.
     If the app server is reachable, use `browser_navigate` to visit the affected page and
     `browser_take_screenshot` to capture the current visual state as evidence.
   - If TEST_SCRIPT_DECAY  → check if imports are valid and locators match current code.
     If the app server is reachable, use `browser_navigate` + `browser_snapshot` to verify
     whether the elements referenced in the test still exist on the live page.

After investigating ALL anomalies, produce a single JSON object matching the schema below.
One DefectAnalysis entry per anomaly — do not skip any.

RESOLUTION ACTION GUIDE:
- NO_ACTION          → transient infra blip, or the test failure is a false positive
- SELF_HEAL_LOCATOR  → the test uses a wrong import path, stale URL, or wrong attribute name;
                       the fix is a small change in the test file only
- SELF_HEAL_LOGIC    → the application code contains an actual bug (wrong return value,
                       missing validation, incorrect calculation); needs a code-fix PR
- ESCALATE_HUMAN     → auth bypass, systemic data corruption, or issue requires
                       architectural understanding; a human engineer must handle it

Your FINAL response must be a single valid JSON object — no markdown fences, no explanation.

{format_instructions}
"""

HUMAN_PROMPT = """
Anomalies to investigate ({count} total):
{anomaly_reports_json}

Test Plan Risk Areas (for prioritization context):
{risk_areas}
"""

_parser = PydanticOutputParser(pydantic_object=DefectIntelligenceOutput)


llm = ChatOpenAI(
    base_url=API_ENDPOINT,
    api_key=API_KEY,
    model=API_MODEL,
    temperature=0.2,
    timeout=180,
    max_retries=2,
)


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


async def defect_intelligence_agent_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node — root-cause analysis on every anomaly from the execution phase."""
    print("--- Running Defect Intelligence Agent ---")

    anomaly_reports = state.get("anomaly_reports", [])

    if not anomaly_reports:
        return {
            "defect_analyses": [],
            "messages": ["Defect Intelligence Agent: No anomalies to analyze."],
        }

    test_plan = state.get("test_plan")

    callbacks = (config or {}).get("callbacks", [])
    system_msg = SYSTEM_PROMPT.format(format_instructions=_parser.get_format_instructions())
    human_msg = HUMAN_PROMPT.format(
        count=len(anomaly_reports),
        anomaly_reports_json="\n\n".join(
            r.model_dump_json(indent=2) for r in anomaly_reports
        ),
        risk_areas=", ".join(test_plan.risk_areas) if test_plan else "N/A",
    )

    client = MultiServerMCPClient(get_mcp_config(playwright=True, leanctx=True))
    mcp_tools = await client.get_tools()
    all_tools = DEFECT_TOOLS + mcp_tools
    agent_subgraph = _build_agent_subgraph(all_tools)

    agent_result = await agent_subgraph.ainvoke(
        {"messages": [("system", system_msg), ("user", human_msg)]},
        config={"callbacks": callbacks, "recursion_limit": 60},
    )

    try:
        output = robust_parse(agent_result["messages"][-1].content, DefectIntelligenceOutput, llm)
        actions = [a.resolution_action for a in output.analyses]
        return {
            "defect_analyses": output.analyses,
            "messages": [
                f"Defect Intelligence Agent completed. "
                f"Analyzed {len(output.analyses)} anomalies. "
                f"Actions: {actions}"
            ],
        }
    except Exception as e:
        print(f"Error parsing Defect Intelligence output: {e}")
        print("Raw output:", agent_result["messages"][-1].content)
        return {
            "defect_analyses": [],
            "messages": [f"Defect Intelligence Agent encountered a parsing error: {e}"],
        }
