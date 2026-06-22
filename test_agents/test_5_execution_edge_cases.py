import os
import sys
import json
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.state import QAuraState, TestPlan, TestComponent, GeneratedTest
from agents.execution_agent import execution_agent_node

def test_execution_edge_cases():
    print("Initializing state for Phase 3 Edge Cases (Infra & Locator Drift)...")
    
    # Mock Test Plan focusing on different risk vectors
    plan = TestPlan(
        project_summary="Mock Edge Cases",
        components=[
            TestComponent(name="database", file_path="db.py", testing_type="Integration", risk_level="High", description="Database connection"),
            TestComponent(name="ui_login", file_path="login.py", testing_type="E2E", risk_level="Medium", description="UI Locator Drift")
        ],
        unit_scope=[],
        integration_scope=["database"],
        e2e_scope=["ui_login"],
        risk_areas=["database"]
    )
    
    # Simulating an INFRASTRUCTURE failure (e.g. Database goes down)
    infra_test = GeneratedTest(
        file_name="test_db_connection_mock.py",
        test_code="def test_db():\n    raise ConnectionError('Connection refused to database on port 5432. 503 Service Unavailable.')",
        framework="pytest",
        target_component="database",
        test_type="integration"
    )
    
    # Simulating a TEST_SCRIPT_DECAY failure (e.g. Frontend team changed a data-testid without updating tests)
    ui_test = GeneratedTest(
        file_name="test_ui_login_mock.py",
        test_code="def test_ui():\n    raise Exception('NoSuchElementException: Unable to locate element with data-testid=\"login-button\"')",
        framework="pytest",
        target_component="ui_login",
        test_type="e2e"
    )
    
    state = {
        "requirements_path": "",
        "test_plan": plan,
        "plan_approved": True,
        "messages": [],
        "unit_tests": [],
        "integration_tests": [infra_test],
        "e2e_tests": [ui_test],
        "execution_summary": None,
        "coverage_confidence": None,
        "anomalies": []
    }
    
    print("\nRunning Execution Agent on Edge Cases...")
    result = execution_agent_node(state)
    
    print("\n--- Edge Case Anomalies Detected ---")
    for anomaly in result.get('anomalies', []):
        print(f"Test Target: {anomaly.affected_component} ({anomaly.test_id})")
        print(f"Classification: {anomaly.classification}")
        print("-" * 50)
        
    report = {
        "execution_summary": result.get('execution_summary').model_dump() if result.get('execution_summary') else None,
        "anomalies": [a.model_dump() for a in result.get('anomalies', [])]
    }
    
    root_dir = Path(__file__).resolve().parent.parent
    report_path = root_dir / "execution_edge_cases_report.json"
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)
        
    print(f"\nEdge case report saved to: {report_path}")

if __name__ == "__main__":
    test_execution_edge_cases()
