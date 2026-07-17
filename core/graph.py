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
import logging
import threading
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parent.parent

from core.state import QAuraState
from core.tools import reset_tests_dir
from agents.planning_agent import test_architect_node, hitl_approval_node
from agents.unit_test_gen import unit_test_gen_node
from agents.integration_test_gen import integration_gen_node
from agents.e2e_test_gen import e2e_gen_node
from agents.execution_agent import execution_agent_node
from agents.reporting_agent import reporting_agent_node
from agents.defect_intelligence_agent import defect_intelligence_agent_node
from agents.self_healing_agent import self_healing_agent_node
from knowledge_graph.graph_store import DefectKnowledgeGraph
from knowledge_graph import graph_builder
from knowledge_graph.graph_query import set_graph as _set_kg_ref

load_dotenv()

MAX_HEALING_ITERATIONS = 3
MAX_PLAN_REVISIONS = 3

KG_PATH = ROOT / "knowledge_graph" / "defect_graph.json"

_kg = DefectKnowledgeGraph()
_kg.load(KG_PATH)
_set_kg_ref(_kg)
_kg_lock = threading.Lock()
_logger = logging.getLogger("qaura.graph")


# ---------------------------------------------------------------------------
# 1. Graph Construction
# ---------------------------------------------------------------------------

def _route_after_approval(state: QAuraState) -> str | list[str]:
    if state.get("plan_approved", False):
        return ["unit_test_gen", "integration_gen", "e2e_gen"]
    if state.get("plan_revision_count", 0) >= MAX_PLAN_REVISIONS:
        return ["unit_test_gen", "integration_gen", "e2e_gen"]
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


async def _test_architect_with_kg(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    result = await test_architect_node(state, config)
    plan = result.get("test_plan") or state.get("test_plan")
    if plan:
        with _kg_lock:
            graph_builder.build_from_test_plan(_kg, plan)
            req_path = state.get("requirements_path", "")
            project_root = Path(req_path).parent if req_path else ROOT
            if project_root == ROOT:
                project_root = ROOT / "demo_app"
            graph_builder.build_dependencies(_kg, project_root.parent if (project_root / "__init__.py").exists() else project_root)
            _kg.save(KG_PATH)
    return result


async def _unit_test_gen_with_kg(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    result = await unit_test_gen_node(state, config)
    tests = result.get("unit_tests", [])
    if tests:
        with _kg_lock:
            graph_builder.build_from_generated_tests(_kg, tests, "unit")
            _kg.save(KG_PATH)
    return result


async def _integration_gen_with_kg(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    result = await integration_gen_node(state, config)
    tests = result.get("integration_tests", [])
    if tests:
        with _kg_lock:
            graph_builder.build_from_generated_tests(_kg, tests, "integration")
            _kg.save(KG_PATH)
    return result


async def _e2e_gen_with_kg(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    result = await e2e_gen_node(state, config)
    tests = result.get("e2e_tests", [])
    if tests:
        with _kg_lock:
            graph_builder.build_from_generated_tests(_kg, tests, "e2e")
            _kg.save(KG_PATH)
    return result


def _run_namespace(state: QAuraState, config: RunnableConfig | None) -> str:
    """Scope defect/heal KG nodes per run AND per healing iteration —
    anomaly IDs restart at ANOM-001 on every execution pass."""
    thread_id = ((config or {}).get("configurable") or {}).get("thread_id", "unknown_run")
    return f"{thread_id}:i{state.get('healing_iterations', 0)}"


async def _execution_with_kg(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    result = await execution_agent_node(state, config)
    anomalies = result.get("anomaly_reports", [])
    if anomalies:
        with _kg_lock:
            graph_builder.build_from_anomalies(_kg, anomalies, run_ns=_run_namespace(state, config))
            _kg.save(KG_PATH)
    return result


async def _self_healing_with_kg(state: QAuraState, config: RunnableConfig | None = None) -> dict:
    result = await self_healing_agent_node(state, config)
    actions = result.get("healing_actions", [])
    if actions:
        with _kg_lock:
            graph_builder.build_from_healing(_kg, actions, run_ns=_run_namespace(state, config))
            _kg.save(KG_PATH)
    return result


def build_graph() -> StateGraph:
    builder = StateGraph(QAuraState)

    # --- Nodes ---
    builder.add_node("test_architect", _test_architect_with_kg)
    builder.add_node("human_approval", hitl_approval_node)
    builder.add_node("unit_test_gen", _unit_test_gen_with_kg)
    builder.add_node("integration_gen", _integration_gen_with_kg)
    builder.add_node("e2e_gen", _e2e_gen_with_kg)
    builder.add_node("execution_agent", _execution_with_kg)
    builder.add_node("reporting_agent", reporting_agent_node)
    builder.add_node("defect_intelligence_agent", defect_intelligence_agent_node)
    builder.add_node("self_healing_agent", _self_healing_with_kg)

    # --- Edges: Phase 1 (Planning) ---
    builder.add_edge(START, "test_architect")
    builder.add_edge("test_architect", "human_approval")
    builder.add_conditional_edges(
        "human_approval",
        _route_after_approval,
        ["unit_test_gen", "integration_gen", "e2e_gen", "test_architect"],
    )

    # --- Edges: Phase 2 (Generation) → Phase 3 (Execution) ---
    # All three generators run in parallel, then fan-in to execution
    builder.add_edge("unit_test_gen", "execution_agent")
    builder.add_edge("integration_gen", "execution_agent")
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
        "plan_revision_count": 0,
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

    removed = reset_tests_dir()
    if removed:
        _logger.info("Cleared %d stale test file(s) from tests/", removed)

    _logger.info("Starting Phase 1")
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
    _logger.info("Resuming Graph")
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
                        _logger.info("[%s] Agent calling tools: %s", subgraph_name, tools)
                    else:
                        _logger.info("[%s] Agent provided a response.", subgraph_name)
            elif node_name == "tools":
                _logger.debug("[%s] Tool execution finished.", subgraph_name)
    else:
        for node_name in update.keys():
            if node_name != "__metadata__":
                _logger.info("[Main Graph] Finished node: %s", node_name)


def _print_final_results(state: dict):
    if state.get("test_plan"):
        _logger.info("Writing Test Plan to File")
        with open(ROOT / "test_plan.json", "w") as f:
            json.dump(state["test_plan"].model_dump(), f, indent=2)

    if state.get("execution_summary"):
        _logger.info("Execution Summary: %s", state["execution_summary"])

    if state.get("qa_report"):
        report = state["qa_report"]
        _logger.info("QA Report — Verdict: %s | Summary: %s | Saved to: %s",
                      report.overall_verdict, report.executive_summary, state.get("report_path"))

    if state.get("defect_analyses"):
        for analysis in state["defect_analyses"]:
            _logger.info("[%s] %s: %s", analysis.anomaly_id,
                         analysis.resolution_action, analysis.confirmed_root_cause)

    if state.get("healing_actions"):
        for action in state["healing_actions"]:
            status = "OK" if action.success else "FAILED"
            _logger.info("[%s] %s (%s): %s", action.anomaly_id,
                         action.action_type, status, action.explanation)
        _logger.info("Loop decision: %s | Healing iterations: %s",
                      state.get("loop_decision"), state.get("healing_iterations"))


async def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")
    _logger.info("Starting QAura Graph...")
    config, _ = await run_pipeline_phase1()

    while True:
        snapshot = graph.get_state(config)
        if not snapshot.next:
            break

        _logger.info("Graph Paused — Waiting for human input...")

        approved = input("Approve the test plan? (y/n): ").lower() == "y"
        feedback = ""
        if not approved:
            feedback = input("Please provide feedback for the plan: ")

        await run_pipeline_phase2(config, approved, feedback)

    final_state = graph.get_state(config).values
    _logger.info("Final Output — Plan Approved: %s", final_state.get("plan_approved"))
    _print_final_results(final_state)


if __name__ == "__main__":
    asyncio.run(main())
