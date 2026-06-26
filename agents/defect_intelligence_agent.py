import os
from dotenv import load_dotenv
from core.state import QAuraState, DefectAnalysis, DefectIntelligenceOutput
from core.tools import DEFECT_TOOLS
from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

load_dotenv()
API_KEY = os.environ.get('DEFECT_AGENT_API_KEY', '')
API_ENDPOINT = os.environ.get('DEFECT_AGENT_ENDPOINT', '')
API_MODEL = os.environ.get('DEFECT_AGENT_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Defect Intelligence Agent.
Your job is to investigate every anomaly from the test execution and determine its true root cause.

For EACH anomaly provided, follow these investigation steps in order:

1. Call `search_codebase` with the affected_component name to retrieve its source code.
2. Call `read_test_file` with the test_id path to read the failing test and understand what it asserts.
3. Based on the classification:
   - If INFRASTRUCTURE  → call `read_server_log` to check for startup/connection errors.
   - If APPLICATION_DEFECT → compare what the test expects vs. what the source code actually does.
   - If TEST_SCRIPT_DECAY  → check if imports are valid and locators match current code.

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
    temperature=0.2,
)

agent = create_tool_calling_agent(llm, DEFECT_TOOLS, prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=DEFECT_TOOLS,
    verbose=True,
    max_iterations=30,  
)


def defect_intelligence_agent_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
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
    agent_result = agent_executor.invoke(
        {
            "count": len(anomaly_reports),
            "anomaly_reports_json": "\n\n".join(
                r.model_dump_json(indent=2) for r in anomaly_reports
            ),
            "risk_areas": ", ".join(test_plan.risk_areas) if test_plan else "N/A",
        },
        config={"callbacks": callbacks},
    )

    try:
        output = robust_parse(agent_result["output"], DefectIntelligenceOutput, llm)
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
        print("Raw output:", agent_result["output"])
        return {
            "defect_analyses": [],
            "messages": [f"Defect Intelligence Agent encountered a parsing error: {e}"],
        }
