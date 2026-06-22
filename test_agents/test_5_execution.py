import os
import sys
import json
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.state import QAuraState, TestPlan, TestComponent, GeneratedTest
from agents.execution_agent import execution_agent_node

def test_execution_phase():
    print("Initializing mock state for Phase 3 testing...")
    
    # Mock Test Plan
    plan = TestPlan(
        project_summary="Mock Project",
        components=[
            TestComponent(name="auth", file_path="auth.py", testing_type="Unit", risk_level="High", description="Authentication module"),
            TestComponent(name="orders", file_path="orders.py", testing_type="E2E", risk_level="Medium", description="Order flow")
        ],
        unit_scope=["auth"],
        integration_scope=[],
        e2e_scope=["orders"],
        risk_areas=["auth"]
    )
    
    # Mock Tests
    unit_test = GeneratedTest(
        file_name="test_auth_mock.py",
        test_code="def test_login(): assert True",
        framework="pytest",
        target_component="auth",
        test_type="unit"
    )
    
    e2e_test = GeneratedTest(
        file_name="test_orders_mock.py",
        test_code="def test_order(): assert False, 'Simulated failure'",
        framework="pytest",
        target_component="orders",
        test_type="e2e"
    )
    
    state = {
        "requirements_path": "",
        "test_plan": plan,
        "plan_approved": True,
        "messages": [],
        "unit_tests": [unit_test],
        "integration_tests": [],
        "e2e_tests": [e2e_test],
        "execution_summary": None,
        "coverage_confidence": None,
        "anomalies": []
    }
    
    print("\nRunning Execution Agent...")
    result = execution_agent_node(state)
    
    print("\n--- Execution Results ---")
    print(f"Summary: {result.get('execution_summary')}")
    print(f"Coverage: {result.get('coverage_confidence')}")
    for i, anomaly in enumerate(result.get('anomalies', [])):
        print(f"Anomaly {i+1}: {anomaly}")

    print("\n--- Writing Execution Report to File ---")
    report = {
        "execution_summary": result.get('execution_summary').model_dump() if result.get('execution_summary') else None,
        "coverage_confidence": result.get('coverage_confidence').model_dump() if result.get('coverage_confidence') else None,
        "anomalies": [a.model_dump() for a in result.get('anomalies', [])]
    }
    
    root_dir = Path(__file__).resolve().parent.parent
    report_path = root_dir / "execution_report.json"
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)
        
    print(f"Execution report saved to: {report_path}")
        
if __name__ == "__main__":
    test_execution_phase()
