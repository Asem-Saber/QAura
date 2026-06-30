import json

from knowledge_graph.graph_store import DefectKnowledgeGraph
from knowledge_graph.graph_query import (
    set_graph,
    query_risk_propagation,
    query_similar_defects,
    query_healing_patterns,
    query_component_health,
)


def _build_test_graph():
    kg = DefectKnowledgeGraph()

    kg.add_node("comp:app/auth.py", "Component", file_path="app/auth.py", name="Auth")
    kg.add_node("comp:app/orders.py", "Component", file_path="app/orders.py", name="Orders")
    kg.add_node("comp:app/server.py", "Component", file_path="app/server.py", name="Server")
    kg.add_node("risk:SQL injection", "RiskArea", name="SQL injection")
    kg.add_node("test:tests/test_auth.py", "TestFile", file_path="tests/test_auth.py", test_type="unit")

    kg.add_edge("comp:app/orders.py", "comp:app/auth.py", "DEPENDS_ON")
    kg.add_edge("comp:app/server.py", "comp:app/auth.py", "DEPENDS_ON")
    kg.add_edge("comp:app/auth.py", "risk:SQL injection", "BELONGS_TO")
    kg.add_edge("test:tests/test_auth.py", "comp:app/auth.py", "COVERS")

    kg.add_node("defect:ANOM-001", "Defect",
                anomaly_id="ANOM-001",
                classification="APPLICATION_DEFECT",
                root_cause="Wrong return in login()",
                error_type="AssertionError",
                pattern_key="AssertionError::app/auth.py::APPLICATION_DEFECT")
    kg.add_edge("defect:ANOM-001", "comp:app/auth.py", "AFFECTS")
    kg.add_edge("defect:ANOM-001", "test:tests/test_auth.py", "DETECTED_BY")

    kg.add_node("heal:ANOM-001", "HealingAction",
                anomaly_id="ANOM-001",
                action_type="SELF_HEAL_LOGIC",
                success=True,
                explanation="Fixed login return value")
    kg.add_edge("heal:ANOM-001", "defect:ANOM-001", "FIXES")

    set_graph(kg)
    return kg


def test_query_risk_propagation():
    _build_test_graph()
    result = json.loads(query_risk_propagation.invoke("app/auth.py"))
    assert result["component"] == "app/auth.py"
    assert set(result["dependents"]) == {"app/orders.py", "app/server.py"}
    assert "SQL injection" in result["risk_areas"]


def test_query_risk_propagation_unknown_component():
    _build_test_graph()
    result = json.loads(query_risk_propagation.invoke("nonexistent.py"))
    assert result["component"] == "nonexistent.py"
    assert result["dependents"] == []


def test_query_similar_defects():
    _build_test_graph()
    result = json.loads(query_similar_defects.invoke({
        "error_type": "AssertionError",
        "component": "app/auth.py",
        "classification": "APPLICATION_DEFECT",
    }))
    assert result["pattern_key"] == "AssertionError::app/auth.py::APPLICATION_DEFECT"
    assert len(result["matches"]) == 1
    assert result["matches"][0]["anomaly_id"] == "ANOM-001"
    assert result["matches"][0]["healing"]["action_type"] == "SELF_HEAL_LOGIC"
    assert result["matches"][0]["healing"]["success"] is True


def test_query_similar_defects_no_matches():
    _build_test_graph()
    result = json.loads(query_similar_defects.invoke({
        "error_type": "TypeError",
        "component": "app/auth.py",
        "classification": "INFRASTRUCTURE",
    }))
    assert result["matches"] == []


def test_query_healing_patterns():
    _build_test_graph()
    result = json.loads(query_healing_patterns.invoke("APPLICATION_DEFECT"))
    assert result["classification"] == "APPLICATION_DEFECT"
    assert len(result["patterns"]) == 1
    assert result["patterns"][0]["action_type"] == "SELF_HEAL_LOGIC"
    assert result["patterns"][0]["success_count"] == 1


def test_query_healing_patterns_no_data():
    _build_test_graph()
    result = json.loads(query_healing_patterns.invoke("INFRASTRUCTURE"))
    assert result["patterns"] == []


def test_query_component_health():
    _build_test_graph()
    result = json.loads(query_component_health.invoke("app/auth.py"))
    assert result["component"] == "app/auth.py"
    assert result["defect_count"] == 1
    assert result["healing_success_rate"] == 1.0
    assert result["test_coverage_count"] == 1
    assert "SQL injection" in result["risk_areas"]
    assert 0.0 <= result["health_score"] <= 1.0


def test_query_component_health_unknown():
    _build_test_graph()
    result = json.loads(query_component_health.invoke("nonexistent.py"))
    assert result["defect_count"] == 0
    assert result["health_score"] == 0.0
