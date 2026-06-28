"""
QAura LangGraph Pipeline — Graph definition and execution API.

Sections:
  1. Graph Construction  — nodes, edges, routing
  2. State Factory       — initial state builder
  3. Pipeline API        — async phase runners (reusable by any frontend)
  4. CLI Runner          — interactive console entry point
"""

import os
import sys
import json
import asyncio
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
from agents.e2e_test_gen import e2e_gen_node
from agents.execution_agent import execution_agent_node
from agents.reporting_agent import reporting_agent_node
from agents.defect_intelligence_agent import defect_intelligence_agent_node
from agents.self_healing_agent import self_healing_agent_node

load_dotenv()

MAX_HEALING_ITERATIONS = 3


# ---------------------------------------------------------------------------
# 1. Graph Construction
# ---------------------------------------------------------------------------

def _route_after_approval(state: QAuraState) -> str:
    if state.get("plan_approved", False):
        return "unit_test_gen"
    return "test_architect"


def _route_after_reporting(state: QAuraState) -> str:
    if state.get("anomaly_reports", []):
        return "defect_intelligence_agent"
    return END


def _route_after_healing(state: QAuraState) -> str:
    if state.get("healing_iterations", 0) > MAX_HEALING_ITERATIONS:
        return END

    decision = state.get("loop_decision", "DONE")
    if decision == "RE_EXECUTE":
        return "execution_agent"
    elif decision == "RE_PLAN":
        return "test_architect"
    return END


def build_graph() -> StateGraph:
    builder = StateGraph(QAuraState)

    # --- Nodes ---
    builder.add_node("test_architect", test_architect_node)
    builder.add_node("human_approval", hitl_approval_node)
    builder.add_node("unit_test_gen", unit_test_gen_node)
    builder.add_node("e2e_gen", e2e_gen_node)
    builder.add_node("execution_agent", execution_agent_node)
    builder.add_node("reporting_agent", reporting_agent_node)
    builder.add_node("defect_intelligence_agent", defect_intelligence_agent_node)
    builder.add_node("self_healing_agent", self_healing_agent_node)

    # --- Edges: Phase 1 (Planning) ---
    builder.add_edge(START, "test_architect")
    builder.add_edge("test_architect", "human_approval")
    builder.add_conditional_edges(
        "human_approval",
        _route_after_approval,
        ["unit_test_gen", "test_architect"],
    )

    # --- Edges: Phase 2 (Generation) → Phase 3 (Execution) ---
    builder.add_edge("unit_test_gen", "e2e_gen")
    builder.add_edge("e2e_gen", "execution_agent")

    # --- Edges: Phase 4 (Reporting → Defect Analysis) ---
    builder.add_edge("execution_agent", "reporting_agent")
    builder.add_conditional_edges(
        "reporting_agent",
        _route_after_reporting,
        ["defect_intelligence_agent", END],
    )

    # --- Edges: Phase 5 (Self-Healing Loop) ---
    builder.add_edge("defect_intelligence_agent", "self_healing_agent")
    builder.add_conditional_edges(
        "self_healing_agent",
        _route_after_healing,
        ["execution_agent", "test_architect", END],
    )

    return builder


def compile_graph():
    builder = build_graph()
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


graph = compile_graph()


# ---------------------------------------------------------------------------
# 2. State Factory
# ---------------------------------------------------------------------------

def get_initial_state(requirements_path: str | None = None) -> dict:
    if requirements_path is None:
        requirements_path = str(ROOT / "project_requirements.md")

    return {
        "requirements_path": requirements_path,
        "messages": [],
        # Phase 1
        "test_plan": None,
        "plan_approved": False,
        # Phase 2
        "unit_tests": [],
        "integration_tests": [],
        "e2e_tests": [],
        # Phase 3-4
        "environment_status": {},
        "execution_summary": None,
        "coverage_assessment": None,
        "anomaly_reports": [],
        "execution_memory": [],
        "qa_report": None,
        "report_path": "",
        # Phase 4
        "defect_analyses": [],
        # Phase 5
        "healing_actions": [],
        "loop_decision": "",
        "healing_iterations": 0,
    }


# ---------------------------------------------------------------------------
# 3. Pipeline API
# ---------------------------------------------------------------------------

async def run_pipeline_phase1(
    requirements_path: str | None = None,
    thread_id: str = "qaura_run_1",
):
    """Run the pipeline until the HITL interrupt. Returns (config, final_state)."""
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = get_initial_state(requirements_path)

    print("\n--- Starting Phase 1 ---")
    async for event in graph.astream(
        initial_state, config=config, stream_mode="updates", subgraphs=True,
    ):
        _log_stream_event(event)

    final_state = graph.get_state(config).values
    return config, final_state


async def run_pipeline_phase2(
    config: dict,
    approved: bool,
    feedback: str = "",
):
    """Resume after HITL with approval decision. Returns the final StateSnapshot."""
    print("\n--- Resuming Graph ---")
    async for event in graph.astream(
        Command(resume={"approved": approved, "feedback": feedback}),
        config=config,
        stream_mode="updates",
        subgraphs=True,
    ):
        _log_stream_event(event)

    return graph.get_state(config)


# ---------------------------------------------------------------------------
# 4. CLI Runner
# ---------------------------------------------------------------------------

def _log_stream_event(event):
    namespace, update = event

    if namespace:
        subgraph_name = namespace[0]
        for node_name, node_update in update.items():
            if node_name == "agent":
                messages = node_update.get("messages", [])
                if messages:
                    last_msg = messages[-1]
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        tools = [tc["name"] for tc in last_msg.tool_calls]
                        print(f"    [{subgraph_name}] Agent calling tools: {tools}")
                    else:
                        print(f"    [{subgraph_name}] Agent provided a response.")
            elif node_name == "tools":
                print(f"    [{subgraph_name}] Tool execution finished.")
    else:
        for node_name in update.keys():
            if node_name != "__metadata__":
                print(f"\n[Main Graph] Finished node: {node_name}")


def _print_final_results(state: dict):
    if state.get("test_plan"):
        print("\n--- Writing Test Plan to File ---")
        with open(ROOT / "test_plan.json", "w") as f:
            json.dump(state["test_plan"].model_dump(), f, indent=2)

    if state.get("execution_summary"):
        print("\n--- Execution Summary ---")
        print(state["execution_summary"])

    if state.get("qa_report"):
        report = state["qa_report"]
        print("\n--- QA Report ---")
        print(f"  Verdict : {report.overall_verdict}")
        print(f"  Summary : {report.executive_summary}")
        print(f"  Saved to: {state.get('report_path')}")

    if state.get("defect_analyses"):
        print("\n--- Defect Analyses ---")
        for analysis in state["defect_analyses"]:
            print(
                f"  [{analysis.anomaly_id}] {analysis.resolution_action}: "
                f"{analysis.confirmed_root_cause}"
            )

    if state.get("healing_actions"):
        print("\n--- Self-Healing Actions ---")
        for action in state["healing_actions"]:
            status = "OK" if action.success else "FAILED"
            print(
                f"  [{action.anomaly_id}] {action.action_type} ({status}): "
                f"{action.explanation}"
            )
        print(f"  Loop decision: {state.get('loop_decision')}")
        print(f"  Healing iterations: {state.get('healing_iterations')}")


async def main():
    print("Starting QAura Graph...")
    config, _ = await run_pipeline_phase1()

    while True:
        snapshot = graph.get_state(config)
        if not snapshot.next:
            break

        print("\n--- Graph Paused ---")
        print("Waiting for human input...")

        approved = input("Approve the test plan? (y/n): ").lower() == "y"
        feedback = ""
        if not approved:
            feedback = input("Please provide feedback for the plan: ")

        await run_pipeline_phase2(config, approved, feedback)

    final_state = graph.get_state(config).values
    print("\n--- Final Output ---")
    print(f"Plan Approved: {final_state.get('plan_approved')}")
    _print_final_results(final_state)


if __name__ == "__main__":
    asyncio.run(main())
