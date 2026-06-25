import os
import ast
import json
from dotenv import load_dotenv
from core.state import (
    QAuraState, 
    ExecutionResultsSummary, 
    CoverageConfidenceAssessment, 
    StructuredAnomalyReport,
    ExecutionMemoryUpdate
)
from core.tools import EXECUTION_TOOLS
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from pydantic import BaseModel, Field
from typing import List

load_dotenv()
API_KEY = os.environ.get('EXECUTION_AGENT_API_KEY', '')
API_ENDPOINT = os.environ.get('EXECUTION_AGENT_ENDPOINT', '')
API_MODEL = os.environ.get('EXECUTION_AGENT_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Execution Agent.
Your mission is to act as an autonomous orchestrator that evaluates, prioritizes, and executes tests.

WORKFLOW:
1. First, call `check_environment_health` to verify if the infrastructure (DB and server) is ready.
   - If the server is unreachable or DB is disconnected, you must record this as a blocked execution and create infrastructure anomaly reports without running tests.
2. If the environment is healthy, call `run_pytest_suite` to execute the tests provided in the `Compiled Test Suites` input.
   - You can pass 'tests/' to run the whole suite at once, or prioritize them individually based on risk.
3. Analyze the raw pytest logs to categorize any failures.
   - INFRASTRUCTURE: 503, Connection Refused, etc.
   - APPLICATION_DEFECT: AssertionError, IndexError, etc.
   - TEST_SCRIPT_DECAY: ElementNotFoundException, etc.
4. Generate the final execution summaries and structured reports.

Your final output must be exactly a valid JSON object matching the ExecutionOutput schema provided.
Ensure you properly populate ExecutionResultsSummary, CoverageConfidenceAssessment, StructuredAnomalyReports, and ExecutionMemoryUpdates.
Do NOT wrap the JSON in markdown code blocks. Just output the raw JSON string.

Output JSON Schema:
{{
  "execution_summary": {{
    "total_tests": int,
    "passed": int,
    "failed": int,
    "blocked": int,
    "execution_duration_ms": int,
    "critical_path_success": bool
  }},
  "coverage_assessment": {{
    "overall_confidence": float,
    "component_scores": [
      {{"component": string, "score": float}}
    ],
    "identified_gaps": [string]
  }},
  "anomaly_reports": [
    {{
      "anomaly_id": string,
      "test_id": string,
      "affected_component": string,
      "classification": "INFRASTRUCTURE" | "APPLICATION_DEFECT" | "TEST_SCRIPT_DECAY",
      "root_cause_hypothesis": string,
      "correlated_stack_trace": string
    }}
  ],
  "execution_memory": [
    {{
      "test_id": string,
      "duration_ms": int,
      "flaky_flag_raised": bool,
      "retry_count": int
    }}
  ]
}}
"""

HUMAN_PROMPT = """Please execute the test suite and provide the analysis.
Test Plan Summary: {project_summary}
Risk Areas: {risk_areas}

Compiled Test Suites (From Phase 2):
{compiled_tests}
"""

class ExecutionOutput(BaseModel):
    execution_summary: ExecutionResultsSummary
    coverage_assessment: CoverageConfidenceAssessment
    anomaly_reports: List[StructuredAnomalyReport]
    execution_memory: List[ExecutionMemoryUpdate]

llm = ChatOpenAI(
    base_url=API_ENDPOINT,
    api_key=API_KEY,
    model=API_MODEL,
    temperature=0.2
).bind(response_format={"type": "json_object"})

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

agent = create_tool_calling_agent(llm, EXECUTION_TOOLS, prompt)
agent_executor = AgentExecutor(agent=agent, tools=EXECUTION_TOOLS, verbose=True, max_iterations=20)

def execution_agent_node(state: QAuraState) -> dict:
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

    agent_result = agent_executor.invoke({
        "project_summary": project_summary,
        "risk_areas": ", ".join(risk_areas),
        "compiled_tests": compiled_tests_str
    })

    try:
        output_str = agent_result["output"].strip()
        
        # Robustly extract JSON block by finding the first '{' and last '}'
        start_idx = output_str.find('{')
        end_idx = output_str.rfind('}')
        if start_idx != -1 and end_idx != -1:
            json_str = output_str[start_idx:end_idx+1]
        else:
            json_str = output_str
            
        data = json.loads(json_str)
        
        # Parse into Pydantic models
        output = ExecutionOutput(**data)
        
        return {
            "execution_summary": output.execution_summary,
            "coverage_assessment": output.coverage_assessment,
            "anomaly_reports": output.anomaly_reports,
            "execution_memory": output.execution_memory,
            "messages": [
                f"Execution Agent completed. {output.execution_summary.passed} passed, "
                f"{output.execution_summary.failed} failed, {output.execution_summary.blocked} blocked."
            ]
        }
    except Exception as e:
        print(f"Error parsing execution output: {e}")
        print("Raw output:", agent_result["output"])
        return {
            "messages": [f"Execution Agent encountered an error during parsing: {e}"]
        }
