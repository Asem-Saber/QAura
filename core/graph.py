import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parent.parent

from core.state import QAuraState
from agents.planning_agent import test_architect_node, hitl_approval_node
from agents.unit_test_gen import unit_test_gen_node
# from agents.integration_test_gen import integration_gen_node
# from agents.e2e_test_gen import e2e_gen_node
from agents.execution_agent import execution_agent_node
from agents.reporting_agent import reporting_agent_node
from agents.defect_intelligence_agent import defect_intelligence_agent_node

load_dotenv()

builder = StateGraph(QAuraState)

builder.add_node("test_architect", test_architect_node)
builder.add_node("human_approval", hitl_approval_node)
builder.add_node("unit_test_gen", unit_test_gen_node)
# builder.add_node("integration_gen", integration_gen_node)
# builder.add_node("e2e_gen", e2e_gen_node)
builder.add_node("execution_agent", execution_agent_node)
builder.add_node("reporting_agent", reporting_agent_node)         
builder.add_node("defect_intelligence_agent", defect_intelligence_agent_node)  

builder.add_edge(START, "test_architect")
builder.add_edge("test_architect", "human_approval")

def route_after_approval(state: QAuraState) -> list[str]:
    if state.get("plan_approved", False):
        return ["unit_test_gen", END]
    return [END]

builder.add_conditional_edges(
    "human_approval",
    route_after_approval,
    ["unit_test_gen", END]
)

builder.add_edge("unit_test_gen", "execution_agent")
# builder.add_edge("integration_gen", "execution_agent")
# builder.add_edge("e2e_gen", "execution_agent")

builder.add_edge("execution_agent", "reporting_agent")

def route_after_reporting(state: QAuraState) -> str:
    """Route to defect analysis if anomalies were found, otherwise end."""
    anomalies = state.get("anomaly_reports", [])
    if anomalies:
        return "defect_intelligence_agent"
    return END

builder.add_conditional_edges(
    "reporting_agent",
    route_after_reporting,
    ["defect_intelligence_agent", END]
)

builder.add_edge("defect_intelligence_agent", END)
memory = MemorySaver()

graph = builder.compile(checkpointer=memory)

def get_initial_state(requirements_path: str = None) -> dict:
    if requirements_path is None:
        requirements_path = str(ROOT / "project_requirements.md")
    return {
        "requirements_path": requirements_path,
        "test_plan": None,
        "plan_approved": False,
        "messages": [],
        "unit_tests": [],
        "integration_tests": [],
        "e2e_tests": [],
        "environment_status": {},
        "execution_summary": None,
        "coverage_assessment": None,
        "anomaly_reports": [],
        "execution_memory": [],
        "qa_report": None,
        "report_path": "",
        "defect_analyses": [],
    }


def run_pipeline_phase1(requirements_path: str = None, thread_id: str = "qaura_run_1"):
    """Run the pipeline until the HITL interrupt. Returns (config, list_of_state_updates)."""
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = get_initial_state(requirements_path)
    updates = []
    for output in graph.stream(initial_state, config=config, stream_mode="values"):
        updates.append(output)
    return config, updates


def run_pipeline_phase2(config: dict, approved: bool):
    """Resume after HITL with approval decision. Returns list of state updates."""
    updates = []
    for output in graph.stream(
        Command(resume={"approved": approved}),
        config=config,
        stream_mode="values",
    ):
        updates.append(output)
    return updates


if __name__ == "__main__":
    print("Starting QAura Graph...")
    config, phase1_updates = run_pipeline_phase1()

    for output in phase1_updates:
        print("Current State Messages:", output.get('messages', []))

    print("\n--- Graph Paused ---")
    print("Waiting for human input...")

    human_input = input("Approve the test plan? (y/n): ")
    is_approved = human_input.lower() == 'y'

    print("\n--- Resuming Graph into Phase 2 ---")
    phase2_updates = run_pipeline_phase2(config, is_approved)

    final_state = phase2_updates[-1] if phase2_updates else None
    print("\n--- Final Output ---")
    print(f"Plan Approved: {final_state.get('plan_approved')}")

    if final_state and final_state.get("test_plan"):
        print("\n--- Writing Test Plan to File ---")
        with open(ROOT / "test_plan.json", "w") as f:
            json.dump(final_state.get("test_plan").model_dump(), f, indent=2)

    if final_state and final_state.get("execution_summary"):
        print("\n--- Execution Summary ---")
        print(final_state.get("execution_summary"))

    if final_state and final_state.get("qa_report"):
        report = final_state["qa_report"]
        print("\n--- QA Report ---")
        print(f"  Verdict : {report.overall_verdict}")
        print(f"  Summary : {report.executive_summary}")
        print(f"  Saved to: {final_state.get('report_path')}")

    if final_state and final_state.get("defect_analyses"):
        print("\n--- Defect Analyses ---")
        for analysis in final_state["defect_analyses"]:
            print(
                f"  [{analysis.anomaly_id}] {analysis.resolution_action}: "
                f"{analysis.confirmed_root_cause}"
            )