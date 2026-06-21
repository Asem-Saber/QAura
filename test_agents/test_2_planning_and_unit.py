import os
import sys

# Ensure the parent directory (QAura) is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from langgraph.graph import StateGraph, START, END
from core.state import QAuraState
from agents.planning_agent import test_architect_node
from agents.unit_test_gen import unit_test_gen_node

def main():
    builder = StateGraph(QAuraState)
    
    # 1. Add the nodes
    builder.add_node("planner", test_architect_node)
    builder.add_node("unit_test_gen", unit_test_gen_node)
    
    # 2. Define edges
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "unit_test_gen")
    builder.add_edge("unit_test_gen", END)
    
    # 3. Compile the graph
    graph = builder.compile()
    
    # 4. Set up the initial state
    req_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'project_requirements.md'))
    if not os.path.exists(req_path):
        print(f"Warning: Requirements file not found at {req_path}")
        
    initial_state = {
        "requirements_path": req_path,
        "test_plan": None,
        "plan_approved": False,
        "messages": [],
        "unit_tests": [],
        "integration_tests": [],
        "e2e_tests": []
    }
    
    print("Running planning -> unit test gen graph...")
    # Optional: use recursion_limit if the graph could loop, but here it's linear.
    result = graph.invoke(initial_state)
    
    print("\n--- Execution Finished ---")
    print("Result messages:")
    for msg in result.get("messages", []):
        print(f"- {msg}")
        
    unit_tests = result.get("unit_tests", [])
    print(f"\nGenerated {len(unit_tests)} unit test files.")

if __name__ == "__main__":
    main()
