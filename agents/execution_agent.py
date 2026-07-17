import os
import logging
from dotenv import load_dotenv
from core.state import (
    QAuraState,
    ExecutionOutput,
    ExecutionResultsSummary,
    CoverageConfidenceAssessment,
    StructuredAnomalyReport,
    ExecutionMemoryUpdate,
)
from core.tools import EXECUTION_TOOLS
from core.output_parsing import robust_parse
from core.memory_db import log_execution
from langchain_openai import ChatOpenAI
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig

load_dotenv()
API_KEY = os.environ.get('EXECUTION_AGENT_API_KEY', '')
API_ENDPOINT = os.environ.get('EXECUTION_AGENT_ENDPOINT', '')
API_MODEL = os.environ.get('EXECUTION_AGENT_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Execution Agent.
Your mission is to act as an autonomous orchestrator that evaluates, prioritizes, and executes tests.

PHASE 1 — TOOL CALLS (you MUST call tools before producing your final answer):

1. Check the Compiled Test Suites for any [E2E] or [INTEGRATION] tests.
   - If present, call `check_environment_health` to verify infrastructure readiness.
     - If the server is unreachable or DB is disconnected, record all tests as BLOCKED
       and classify the anomaly as INFRASTRUCTURE. Do NOT call run_pytest_suite.
   - If only [UNIT] tests are present, skip the environment check — unit tests are
     fully isolated and do not require external infrastructure.

2. If you are cleared to proceed (environment is healthy, or unit-only run),
   call `run_pytest_suite` to execute the tests.
   - Pass 'tests/' to run the entire suite, or 'tests/<filename>.py' for individual files.
   - Prioritize high-risk components first when running individually.

3. `run_pytest_suite` returns JSON with a `deterministic_summary` (exact measured
   counts, durations, per-file results, and the list of failed tests) plus a
   `raw_output_tail` with tracebacks. Use the summary for all numbers; use the
   raw output only to understand WHY tests failed.

4. After execution, call `query_test_history` for each test file that appeared in the run.
   Use the historical data to enrich your analysis — compare current results against past
   flakiness rates and durations.

PHASE 2 — ANALYSIS (after all tool calls are complete):

Categorize each failure from the pytest logs:
- INFRASTRUCTURE: connection refused, 503, timeout, DB unreachable
- APPLICATION_DEFECT: AssertionError, TypeError, IndexError, logic failures
- TEST_SCRIPT_DECAY: ElementNotFoundException, stale locator, import error in test file

SCORING RULES (use these to populate the output fields):
- total_tests / passed / failed / blocked / execution_duration_ms: copy VERBATIM from
  the `deterministic_summary.totals` returned by run_pytest_suite. These are measured
  values — never estimate, recompute, or read them from the raw text output.
  If deterministic_summary is null (collection crash), all tests are blocked.
- critical_path_success: TRUE if all components marked High-risk have >50% pass rate
  (use `deterministic_summary.per_file` counts). FALSE if any High-risk component has
  majority failures or is entirely blocked.
- overall_confidence: (passed / total_tests) from the deterministic totals, as a float
  between 0.0 and 1.0. If no tests ran, use 0.0.
- component_scores: for each component, compute (passed_in_component / total_in_component)
  from `deterministic_summary.per_file`, mapping files to components via the test plan.
- identified_gaps: list components from the test plan that have NO test files present,
  or components where all tests are blocked/errored.
- duration_ms per test file (execution_memory): use `deterministic_summary.per_file[...].duration_ms`.
- flaky_flag_raised: set to true if query_test_history returned a flakiness_rate > 0.1 for this test,
  OR if the test passed in a previous run but failed now without code changes.
- retry_count: always 0 (no retry configured in this environment).
- anomaly_id: use sequential format "ANOM-001", "ANOM-002", etc.

PHASE 3 — FINAL OUTPUT:

Once you have gathered all information via tools, your FINAL response must be a single
valid JSON object (no markdown fences, no explanation) matching this schema:

{format_instructions}
"""

HUMAN_PROMPT = """Please execute the test suite and provide the analysis.
Test Plan Summary: {project_summary}
Risk Areas: {risk_areas}

Compiled Test Suites (From Phase 2):
{compiled_tests}
"""

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

_exec_parser = PydanticOutputParser(pydantic_object=ExecutionOutput)


def _build_agent_subgraph():
    llm_with_tools = llm.bind_tools(EXECUTION_TOOLS)

    def call_model(state: AgentState):
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(EXECUTION_TOOLS, handle_tool_errors=True))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()


async def execution_agent_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node — executes tests and analyzes results."""
    logger = logging.getLogger("qaura.execution")
    logger.info("Running Execution Agent")
    test_plan = state.get("test_plan")

    project_summary = test_plan.project_summary if test_plan else "No test plan"
    risk_areas = test_plan.risk_areas if test_plan else []

    unit_tests = state.get("unit_tests", [])
    integration_tests = state.get("integration_tests", [])
    e2e_tests = state.get("e2e_tests", [])

    compiled_tests = []
    for t in unit_tests:
        compiled_tests.append(f"- [UNIT] {t.file_name} (Target: {t.target_component})")
    for t in integration_tests:
        compiled_tests.append(f"- [INTEGRATION] {t.file_name} (Target: {t.target_component})")
    for t in e2e_tests:
        compiled_tests.append(f"- [E2E] {t.file_name} (Target: {t.target_component})")

    compiled_tests_str = "\n".join(compiled_tests) if compiled_tests else "No tests found in state."

    callbacks = (config or {}).get("callbacks", [])
    system_msg = SYSTEM_PROMPT.format(format_instructions=_exec_parser.get_format_instructions())
    human_msg = HUMAN_PROMPT.format(
        project_summary=project_summary,
        risk_areas=", ".join(risk_areas),
        compiled_tests=compiled_tests_str,
    )

    agent_subgraph = _build_agent_subgraph()
    agent_result = await agent_subgraph.ainvoke(
        {"messages": [("system", system_msg), ("user", human_msg)]},
        config={"callbacks": callbacks, "recursion_limit": 60},
    )

    try:
        output = robust_parse(agent_result["messages"][-1].content, ExecutionOutput, llm)

        run_id = (config or {}).get("configurable", {}).get("thread_id", "unknown_run")
        failed_test_ids = {a.test_id for a in output.anomaly_reports}
        anomaly_map = {a.test_id: a for a in output.anomaly_reports}

        for mem in output.execution_memory:
            status = "failed" if mem.test_id in failed_test_ids else "passed"
            anomaly = anomaly_map.get(mem.test_id)
            log_execution(
                test_id=mem.test_id,
                run_id=run_id,
                status=status,
                duration_ms=mem.duration_ms,
                stack_trace=anomaly.correlated_stack_trace if anomaly else "",
                classification=anomaly.classification if anomaly else "",
            )

        return {
            "execution_summary": output.execution_summary,
            "coverage_assessment": output.coverage_assessment,
            "anomaly_reports": output.anomaly_reports,
            "execution_memory": output.execution_memory,
            "environment_status": {"parsed": True},
            "messages": [
                f"Execution Agent completed. {output.execution_summary.passed} passed, "
                f"{output.execution_summary.failed} failed, {output.execution_summary.blocked} blocked."
            ]
        }
    except Exception as e:
        logger.error("Error parsing execution output: %s", e)
        logger.debug("Raw output: %s", agent_result["messages"][-1].content)
        return {
            "environment_status": {"parsed": False, "error": str(e)},
            "messages": [f"Execution Agent encountered an error during parsing: {e}"]
        }
