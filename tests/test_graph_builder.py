import tempfile
import textwrap
from pathlib import Path

from knowledge_graph.graph_store import DefectKnowledgeGraph
from knowledge_graph.graph_builder import (
    build_from_test_plan,
    build_dependencies,
    build_from_generated_tests,
    build_from_anomalies,
    build_from_healing,
)
from core.state import (
    TestPlan,
    TestComponent,
    GeneratedTest,
    StructuredAnomalyReport,
    HealingAction,
)


def _make_test_plan():
    return TestPlan(
        project_summary="Demo e-commerce app",
        components=[
            TestComponent(
                name="Auth Module",
                file_path="demo_app/auth.py",
                testing_type="Unit",
                risk_level="High",
                description="Authentication and session management",
            ),
            TestComponent(
                name="Orders Module",
                file_path="demo_app/orders.py",
                testing_type="Integration",
                risk_level="Medium",
                description="Product and order logic",
            ),
        ],
        unit_scope=["Auth Module"],
        integration_scope=["Orders Module"],
        e2e_scope=[],
        risk_areas=["SQL injection", "Session expiry"],
    )


def test_build_from_test_plan_creates_component_nodes():
    kg = DefectKnowledgeGraph()
    plan = _make_test_plan()
    build_from_test_plan(kg, plan)

    auth = kg.get_node("comp:demo_app/auth.py")
    assert auth is not None
    assert auth["node_type"] == "Component"
    assert auth["name"] == "Auth Module"

    orders = kg.get_node("comp:demo_app/orders.py")
    assert orders is not None


def test_build_from_test_plan_creates_risk_nodes():
    kg = DefectKnowledgeGraph()
    plan = _make_test_plan()
    build_from_test_plan(kg, plan)

    sql_risk = kg.get_node("risk:SQL injection")
    assert sql_risk is not None
    assert sql_risk["node_type"] == "RiskArea"


def test_build_from_test_plan_links_high_risk_components():
    kg = DefectKnowledgeGraph()
    plan = _make_test_plan()
    build_from_test_plan(kg, plan)

    neighbors = kg.get_neighbors("comp:demo_app/auth.py", relation="BELONGS_TO", direction="outgoing")
    risk_ids = [nid for nid, _ in neighbors]
    assert len(risk_ids) >= 1


def test_build_dependencies_from_ast():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:pkg/a.py", "Component", name="A")
    kg.add_node("comp:pkg/b.py", "Component", name="B")

    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("from pkg.b import something\n")
        (pkg / "b.py").write_text("something = 42\n")

        build_dependencies(kg, Path(tmp))

    deps = kg.get_neighbors("comp:pkg/a.py", relation="DEPENDS_ON", direction="outgoing")
    assert len(deps) == 1
    assert deps[0][0] == "comp:pkg/b.py"


def test_build_dependencies_ignores_stdlib():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:pkg/a.py", "Component", name="A")

    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("import os\nimport json\n")

        build_dependencies(kg, Path(tmp))

    deps = kg.get_neighbors("comp:pkg/a.py", relation="DEPENDS_ON", direction="outgoing")
    assert len(deps) == 0


def test_build_from_generated_tests():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:demo_app/auth.py", "Component", name="Auth Module")

    tests = [
        GeneratedTest(
            file_name="test_auth.py",
            test_code="def test_login(): pass",
            framework="pytest",
            target_component="Auth Module",
            test_type="unit",
        )
    ]
    build_from_generated_tests(kg, tests, "unit")

    test_node = kg.get_node("test:tests/test_auth.py")
    assert test_node is not None
    assert test_node["test_type"] == "unit"

    covers = kg.get_neighbors("test:tests/test_auth.py", relation="COVERS", direction="outgoing")
    assert len(covers) == 1
    assert covers[0][0] == "comp:demo_app/auth.py"


def test_build_from_anomalies():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:demo_app/auth.py", "Component", name="Auth Module")
    kg.add_node("test:tests/test_auth.py", "TestFile", test_type="unit")

    anomalies = [
        StructuredAnomalyReport(
            anomaly_id="ANOM-001",
            test_id="tests/test_auth.py",
            affected_component="demo_app/auth.py",
            classification="APPLICATION_DEFECT",
            root_cause_hypothesis="Wrong return value in login()",
            correlated_stack_trace="AssertionError: expected True",
        )
    ]
    build_from_anomalies(kg, anomalies)

    defect = kg.get_node("defect:ANOM-001")
    assert defect is not None
    assert defect["classification"] == "APPLICATION_DEFECT"
    assert defect["pattern_key"] == "AssertionError::demo_app/auth.py::APPLICATION_DEFECT"

    affects = kg.get_neighbors("defect:ANOM-001", relation="AFFECTS", direction="outgoing")
    assert len(affects) == 1
    assert affects[0][0] == "comp:demo_app/auth.py"

    detected = kg.get_neighbors("defect:ANOM-001", relation="DETECTED_BY", direction="outgoing")
    assert len(detected) == 1
    assert detected[0][0] == "test:tests/test_auth.py"


def test_build_from_anomalies_links_pattern_matches():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:demo_app/auth.py", "Component", name="Auth Module")
    kg.add_node("test:tests/test_auth.py", "TestFile", test_type="unit")

    kg.add_node("defect:ANOM-OLD", "Defect",
                pattern_key="AssertionError::demo_app/auth.py::APPLICATION_DEFECT",
                anomaly_id="ANOM-OLD")

    anomalies = [
        StructuredAnomalyReport(
            anomaly_id="ANOM-002",
            test_id="tests/test_auth.py",
            affected_component="demo_app/auth.py",
            classification="APPLICATION_DEFECT",
            root_cause_hypothesis="Same bug reappeared",
            correlated_stack_trace="AssertionError: expected True",
        )
    ]
    build_from_anomalies(kg, anomalies)

    pattern_links = kg.get_neighbors("defect:ANOM-002", relation="HAS_PATTERN", direction="outgoing")
    assert len(pattern_links) == 1
    assert pattern_links[0][0] == "defect:ANOM-OLD"


def test_build_from_healing():
    kg = DefectKnowledgeGraph()
    kg.add_node("defect:ANOM-001", "Defect", anomaly_id="ANOM-001")
    kg.add_node("test:tests/test_auth.py", "TestFile", test_type="unit")

    actions = [
        HealingAction(
            anomaly_id="ANOM-001",
            action_type="SELF_HEAL_LOCATOR",
            target_file="tests/test_auth.py",
            original_code="old",
            patched_code="new",
            explanation="Fixed import path",
            success=True,
        )
    ]
    build_from_healing(kg, actions)

    heal = kg.get_node("heal:ANOM-001")
    assert heal is not None
    assert heal["success"] is True

    fixes = kg.get_neighbors("heal:ANOM-001", relation="FIXES", direction="outgoing")
    assert len(fixes) == 1
    assert fixes[0][0] == "defect:ANOM-001"

    modifies = kg.get_neighbors("heal:ANOM-001", relation="MODIFIES", direction="outgoing")
    assert len(modifies) == 1
    assert modifies[0][0] == "test:tests/test_auth.py"
