import os
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
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

load_dotenv()
API_KEY = os.environ.get('EXECUTION_AGENT_API_KEY', '')
API_ENDPOINT = os.environ.get('EXECUTION_AGENT_ENDPOINT', '')
API_MODEL = os.environ.get('EXECUTION_AGENT_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Execution Agent.
Your mission is to act as an autonomous orchestrator that evaluates, prioritizes, and executes tests.

PHASE 1 — TOOL CALLS (you MUST call tools before producing your final answer):

1. Call `check_environment_health` to verify infrastructure readiness.
   - If the server is unreachable or DB is disconnected, record all tests as BLOCKED
     and classify the anomaly as INFRASTRUCTURE. Do NOT call run_pytest_suite.

2. If the environment is healthy, call `run_pytest_suite` to execute the tests.
   - Pass 'tests/' to run the entire suite, or 'tests/<filename>.py' for individual files.
   - Prioritize high-risk components first when running individually.

3. Read and analyze the raw pytest output from each run.

PHASE 2 — ANALYSIS (after all tool calls are complete):

Categorize each failure from the pytest logs:
- INFRASTRUCTURE: connection refused, 503, timeout, DB unreachable
- APPLICATION_DEFECT: AssertionError, TypeError, IndexError, logic failures
- TEST_SCRIPT_DECAY: ElementNotFoundException, stale locator, import error in test file

SCORING RULES (use these to populate the output fields):
- total_tests / passed / failed / blocked: extract from pytest's summary line
  (e.g., "21 passed, 7 failed in 0.22s"). Tests that error during collection = blocked.
- execution_duration_ms: extract total time from pytest output, convert to milliseconds.
- critical_path_success: TRUE if all components marked High-risk have >50% pass rate.
  FALSE if any High-risk component has majority failures or is entirely blocked.
- overall_confidence: (passed / total_tests) as a float between 0.0 and 1.0.
  If no tests ran, use 0.0.
- component_scores: for each component, compute (passed_in_component / total_in_component).
  Group tests by their target component from the file names or test plan.
- identified_gaps: list components from the test plan that have NO test files present,
  or components where all tests are blocked/errored.
- flaky_flag_raised: always false (single run — no flakiness signal available).
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
    temperature=0.2
)

_exec_parser = PydanticOutputParser(pydantic_object=ExecutionOutput)

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])
prompt = prompt.partial(format_instructions=_exec_parser.get_format_instructions())

agent = create_tool_calling_agent(llm, EXECUTION_TOOLS, prompt)
agent_executor = AgentExecutor(agent=agent, tools=EXECUTION_TOOLS, verbose=True, max_iterations=20)

def execution_agent_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node — executes tests and analyzes results."""
    print("--- Running Execution Agent ---")
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
    agent_result = agent_executor.invoke(
        {
            "project_summary": project_summary,
            "risk_areas": ", ".join(risk_areas),
            "compiled_tests": compiled_tests_str,
        },
        config={"callbacks": callbacks},
    )

    try:
        output = robust_parse(agent_result["output"], ExecutionOutput, llm)

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
        print(f"Error parsing execution output: {e}")
        print("Raw output:", agent_result["output"])
        return {
            "environment_status": {"parsed": False, "error": str(e)},
            "messages": [f"Execution Agent encountered an error during parsing: {e}"]
        }
