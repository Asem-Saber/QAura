import os
from dotenv import load_dotenv
from core.state import QAuraState, QAReport
from core.tools import REPORTING_TOOLS
from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

load_dotenv()
API_KEY = os.environ.get('REPORTING_API_KEY', '')
API_ENDPOINT = os.environ.get('REPORTING_ENDPOINT', '')
API_MODEL = os.environ.get('REPORTING_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Reporting Agent.
Your job is to synthesize raw execution data into a clear, professional QA report.

YOUR STEPS:
1. Call `get_timestamp` to get the current UTC time for the report header.
2. Compose the full report content in Markdown with the following ordered sections:
   - **Executive Summary**: 2-3 plain-English sentences. No jargon. State what passed, what failed, and the overall health.
   - **Execution Metrics**: A Markdown table with columns: Metric | Value.
     Rows: Total Tests, Passed, Failed, Blocked, Duration (ms), Critical Path Success.
   - **Coverage Confidence**: Overall confidence score (0.0-1.0), a per-component Markdown table
     (Component | Score), and a bulleted list of identified gaps.
   - **Anomaly Log**: For each anomaly — a row in a Markdown table with columns:
     ID | Component | Classification | Root Cause Hypothesis.
     If no anomalies, write "No anomalies detected."
   - **Risk Verdict**: State PASS / PASS_WITH_WARNINGS / FAIL / BLOCKED with one sentence justification.

3. Call `write_report_file` with file_name='qa_report_{run_id}.md' and the full Markdown content.
4. Your FINAL response must be a single valid JSON object — no markdown fences, no explanation.

VERDICT RULES (apply strictly):
- BLOCKED   → critical_path_success is False AND blocked > 0 AND passed == 0
- FAIL      → failed > 0 AND critical_path_success is False
- PASS_WITH_WARNINGS → failed > 0 AND critical_path_success is True
- PASS      → failed == 0 AND blocked == 0

{format_instructions}
"""

HUMAN_PROMPT = """
run_id: {run_id}

Execution Summary:
{execution_summary}

Coverage Assessment:
{coverage_assessment}

Anomaly Reports:
{anomaly_reports}

Original Test Plan Summary:
{project_summary}
Risk Areas: {risk_areas}
"""

_parser = PydanticOutputParser(pydantic_object=QAReport)

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])
prompt = prompt.partial(format_instructions=_parser.get_format_instructions())

llm = ChatOpenAI(
    base_url=API_ENDPOINT,
    api_key=API_KEY,
    model=API_MODEL,
    temperature=0.1,
)

agent = create_tool_calling_agent(llm, REPORTING_TOOLS, prompt)
agent_executor = AgentExecutor(agent=agent, tools=REPORTING_TOOLS, verbose=True, max_iterations=10)


def reporting_agent_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    """LangGraph node — compiles the QA report from execution results."""
    print("--- Running Reporting Agent ---")

    execution_summary   = state.get("execution_summary")
    coverage_assessment = state.get("coverage_assessment")
    anomaly_reports     = state.get("anomaly_reports", [])
    test_plan           = state.get("test_plan")

    run_id = (config or {}).get("configurable", {}).get("thread_id", "qaura_run_unknown")

    callbacks = (config or {}).get("callbacks", [])
    agent_result = agent_executor.invoke(
        {
            "run_id": run_id,
            "execution_summary": (
                execution_summary.model_dump_json(indent=2)
                if execution_summary else "{}"
            ),
            "coverage_assessment": (
                coverage_assessment.model_dump_json(indent=2)
                if coverage_assessment else "{}"
            ),
            "anomaly_reports": (
                "\n".join(r.model_dump_json() for r in anomaly_reports)
                if anomaly_reports else "None"
            ),
            "project_summary": test_plan.project_summary if test_plan else "N/A",
            "risk_areas": ", ".join(test_plan.risk_areas) if test_plan else "N/A",
        },
        config={"callbacks": callbacks},
    )

    try:
        output = robust_parse(agent_result["output"], QAReport, llm)
        return {
            "qa_report": output,
            "report_path": f"reports/qa_report_{run_id}.md",
            "messages": [
                f"Reporting Agent completed. Verdict: {output.overall_verdict}. "
                f"Report saved to reports/qa_report_{run_id}.md"
            ],
        }
    except Exception as e:
        print(f"Error parsing Reporting Agent output: {e}")
        print("Raw output:", agent_result["output"])
        return {
            "qa_report": None,
            "report_path": "",
            "messages": [f"Reporting Agent encountered a parsing error: {e}"],
        }
