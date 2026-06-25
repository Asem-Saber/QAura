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
from agents.integration_test_gen import integration_gen_node
from agents.e2e_test_gen import e2e_gen_node
from agents.execution_agent import execution_agent_node

load_dotenv()

builder = StateGraph(QAuraState)

builder.add_node("test_architect", test_architect_node)
builder.add_node("human_approval", hitl_approval_node)
builder.add_node("unit_test_gen", unit_test_gen_node)
builder.add_node("integration_gen", integration_gen_node)
builder.add_node("e2e_gen", e2e_gen_node)
builder.add_node("execution_agent", execution_agent_node)

builder.add_edge(START, "test_architect")
builder.add_edge("test_architect", "human_approval")

def route_after_approval(state: QAuraState) -> list[str]:
    if state.get("plan_approved", False):
        return ["unit_test_gen", "integration_gen", "e2e_gen"]
    return [END]

builder.add_conditional_edges(
    "human_approval",
    route_after_approval,
    ["unit_test_gen", "integration_gen", "e2e_gen", END]
)

builder.add_edge("unit_test_gen", "execution_agent")
builder.add_edge("integration_gen", "execution_agent")
builder.add_edge("e2e_gen", "execution_agent")
builder.add_edge("execution_agent", END)
memory = MemorySaver()

graph = builder.compile(checkpointer=memory)

if __name__ == "__main__": 
    print("Starting QAura Graph...")
    config = {"configurable": {"thread_id": "qaura_run_1"}}  
    
    events = graph.stream({"requirements_path": str(ROOT / "project_requirements.md")}, config=config, stream_mode="values")
    
    for output in events:
        print("Current State Messages:", output.get('messages', []))
    
    print("\n--- Graph Paused ---")
    print("Waiting for human input...")
    
    human_input = input("Approve the test plan? (y/n): ")
    is_approved = human_input.lower() == 'y'

    print("\n--- Resuming Graph into Phase 2 ---")
    resume_events = graph.stream(
        Command(resume={"approved": is_approved}), 
        config=config, 
        stream_mode="values"
    )

    final_state = None
    for output in resume_events:
        final_state = output
    print("\n--- Final Output ---")
    print(f"Plan Approved: {final_state.get('plan_approved')}")

    if final_state and final_state.get("test_plan"):
        print("\n--- Writing Test Plan to File ---")
        with open(ROOT / "test_plan.json", "w") as f:
            json.dump(final_state.get("test_plan").model_dump(), f, indent=2)

    if final_state and final_state.get("execution_summary"):
        print("\n--- Execution Summary ---")
        print(final_state.get("execution_summary"))