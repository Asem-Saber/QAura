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

load_dotenv()


def _route_after_approval(state: QAuraState) -> str:
    if state.get("plan_approved", False):
        return END
    return "test_architect"


def build_graph() -> StateGraph:
    builder = StateGraph(QAuraState)

    builder.add_node("test_architect", test_architect_node)
    builder.add_node("human_approval", hitl_approval_node)

    builder.add_edge(START, "test_architect")
    builder.add_edge("test_architect", "human_approval")
    builder.add_conditional_edges(
        "human_approval",
        _route_after_approval,
        ["test_architect", END],
    )

    return builder


def compile_graph():
    builder = build_graph()
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


graph = compile_graph()


def get_initial_state(requirements_path: str | None = None) -> dict:
    if requirements_path is None:
        requirements_path = str(ROOT / "project_requirements.md")

    return {
        "requirements_path": requirements_path,
        "messages": [],
        "test_plan": None,
        "plan_approved": False,
    }


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
    """Resume after HITL with approval decision."""
    print("\n--- Resuming Graph ---")
    async for event in graph.astream(
        Command(resume={"approved": approved, "feedback": feedback}),
        config=config,
        stream_mode="updates",
        subgraphs=True,
    ):
        _log_stream_event(event)

    return graph.get_state(config)


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
