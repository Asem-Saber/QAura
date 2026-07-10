import os
import logging
from dotenv import load_dotenv
from core.state import QAuraState, SelfHealingOutput
from core.tools import SELF_HEALING_TOOLS
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
API_KEY = os.environ.get('HEALING_AGENT_API_KEY', '')
API_ENDPOINT = os.environ.get('HEALING_AGENT_ENDPOINT', '')
API_MODEL = os.environ.get('HEALING_AGENT_MODEL_ID', '')

MAX_HEALING_ITERATIONS = 3

SYSTEM_PROMPT = """You are the QAura Self-Healing Agent.
Your job is to fix broken tests or application code based on root-cause analyses from the Defect Intelligence Agent.

For EACH DefectAnalysis, follow these steps based on the resolution_action:

## BEFORE ANY HEALING
- Call `query_test_history` with the test_id to check the Long-Term Memory for past healing
  actions and execution patterns. If a test has been healed multiple times before, note this
  in your explanation — recurring heals on the same test may indicate a deeper issue.
- Call `query_healing_patterns` with the defect's classification to see which healing
  strategies have historically succeeded. Prioritize action types with higher success rates.

## SELF_HEAL_LOCATOR (test script fix)
1. Call `read_test_file` with the test_id to read the failing test.
2. Call `ctx_read` with `mode=signatures` on the component file to understand
   the current API surface. Then use `ctx_search` to find the correct import
   paths, function signatures, and URLs. Fall back to `search_codebase` for
   broad semantic queries.
3. Identify the stale locator, import path, or attribute name.
4. If the app server is reachable, use `browser_navigate` and `browser_snapshot` to verify
   the correct element selectors on the live page before patching.
5. Call `patch_file` with the exact old code and the corrected new code.
6. Call `run_single_test` to verify the fix works.
7. If the test still fails after your patch, try ONE more iteration. If it still fails, mark success=false.
8. Call `log_healing_action` to record the fix in the Long-Term Memory database, passing the
   anomaly_id, action_type='SELF_HEAL_LOCATOR', target_file, original_code, patched_code,
   explanation, and success status.

## SELF_HEAL_LOGIC (application code fix)
1. Call `ctx_read` with `mode=full` on the affected component's file path to
   get the complete implementation with context compression.
2. Call `ctx_search` to understand the expected behavior from requirements/tests.
   Fall back to `search_codebase` for broad semantic queries.
3. Identify the bug (wrong return value, missing validation, incorrect calculation).
4. Call `validate_python_syntax` on your proposed fix before applying.
5. Call `patch_file` to apply the fix to the application source code.
6. Call `run_single_test` to verify the test now passes with the fix.
7. Call `log_healing_action` to record the fix in the Long-Term Memory database, passing the
   anomaly_id, action_type='SELF_HEAL_LOGIC', target_file, original_code, patched_code,
   explanation, and success status.

## NO_ACTION
- Skip. Record the action with explanation "Transient failure, no fix needed."

## ESCALATE_HUMAN
- Do NOT attempt any fix. Record the action with a clear explanation of why this requires human intervention.

## RULES
- Never delete test files or remove test functions.
- Never change test assertions to match broken behavior — that hides bugs.
- Maximum 2 patch attempts per anomaly. If both fail, mark success=false.
- Always validate syntax before patching.
- Your FINAL response must be a single valid JSON object matching the schema below.

## LOOP DECISION LOGIC
After processing all anomalies, set loop_decision:
- RE_EXECUTE: At least one SELF_HEAL_LOCATOR succeeded (test was fixed, needs re-run)
- RE_PLAN: At least one SELF_HEAL_LOGIC succeeded (app code was fixed, needs re-evaluation)
- ESCALATE: All remaining issues need human intervention
- DONE: All were NO_ACTION or all patches failed

{format_instructions}
"""

HUMAN_PROMPT = """
Defect Analyses to heal ({count} total):
{defect_analyses_json}

Current healing iteration: {iteration} / {max_iterations}

Test Plan Context:
- Project: {project_summary}
- Risk Areas: {risk_areas}
"""

_parser = PydanticOutputParser(pydantic_object=SelfHealingOutput)


llm = ChatOpenAI(
    base_url=API_ENDPOINT,
    api_key=API_KEY,
    model=API_MODEL,
    temperature=0.1,
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


async def self_healing_agent_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node — applies corrective patches based on defect analyses."""
    logger = logging.getLogger("qaura.self_healing")
    logger.info("Running Self-Healing Agent")

    defect_analyses = state.get("defect_analyses", [])
    iteration = state.get("healing_iterations", 0) + 1

    if not defect_analyses:
        return {
            "healing_actions": [],
            "loop_decision": "DONE",
            "healing_iterations": iteration,
            "messages": ["Self-Healing Agent: No defects to heal."],
        }

    if iteration > MAX_HEALING_ITERATIONS:
        return {
            "healing_actions": [],
            "loop_decision": "ESCALATE",
            "healing_iterations": iteration,
            "messages": [
                f"Self-Healing Agent: Max iterations ({MAX_HEALING_ITERATIONS}) reached. "
                "Escalating all remaining issues to human."
            ],
        }

    actionable = [d for d in defect_analyses if d.resolution_action != "NO_ACTION"]
    if not actionable:
        return {
            "healing_actions": [],
            "loop_decision": "DONE",
            "healing_iterations": iteration,
            "messages": ["Self-Healing Agent: All defects are NO_ACTION. Nothing to heal."],
        }

    test_plan = state.get("test_plan")

    callbacks = (config or {}).get("callbacks", [])
    system_msg = SYSTEM_PROMPT.format(format_instructions=_parser.get_format_instructions())
    human_msg = HUMAN_PROMPT.format(
        count=len(actionable),
        defect_analyses_json="\n\n".join(
            d.model_dump_json(indent=2) for d in actionable
        ),
        iteration=iteration,
        max_iterations=MAX_HEALING_ITERATIONS,
        project_summary=test_plan.project_summary if test_plan else "N/A",
        risk_areas=", ".join(test_plan.risk_areas) if test_plan else "N/A",
    )

    async with MultiServerMCPClient(get_mcp_config(playwright=True, leanctx=True)) as client:
        mcp_tools = await client.get_tools()
        all_tools = SELF_HEALING_TOOLS + mcp_tools
        agent_subgraph = _build_agent_subgraph(all_tools)

        agent_result = await agent_subgraph.ainvoke(
            {"messages": [("system", system_msg), ("user", human_msg)]},
            config={"callbacks": callbacks, "recursion_limit": 80},
        )

    try:
        output = robust_parse(agent_result["messages"][-1].content, SelfHealingOutput, llm)
        return {
            "healing_actions": output.actions,
            "loop_decision": output.loop_decision,
            "healing_iterations": iteration,
            "messages": [
                f"Self-Healing Agent (iteration {iteration}): "
                f"Processed {len(output.actions)} defects. "
                f"Loop decision: {output.loop_decision}"
            ],
        }
    except Exception as e:
        logger.error("Error parsing Self-Healing output: %s", e)
        logger.debug("Raw output: %s", agent_result["messages"][-1].content)
        return {
            "healing_actions": [],
            "loop_decision": "ESCALATE",
            "healing_iterations": iteration,
            "messages": [f"Self-Healing Agent encountered a parsing error: {e}. Escalating."],
        }
