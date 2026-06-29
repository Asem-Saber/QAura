import ast
from pathlib import Path

from knowledge_graph.graph_store import DefectKnowledgeGraph
from core.state import TestPlan, GeneratedTest, StructuredAnomalyReport, HealingAction


def build_from_test_plan(graph: DefectKnowledgeGraph, test_plan: TestPlan) -> None:
    for comp in test_plan.components:
        graph.add_node(
            f"comp:{comp.file_path}",
            "Component",
            file_path=comp.file_path,
            name=comp.name,
            risk_level=comp.risk_level,
        )

    for risk_name in test_plan.risk_areas:
        graph.add_node(f"risk:{risk_name}", "RiskArea", name=risk_name)

    for comp in test_plan.components:
        if comp.risk_level == "High":
            for risk_name in test_plan.risk_areas:
                graph.add_edge(f"comp:{comp.file_path}", f"risk:{risk_name}", "BELONGS_TO")


def build_dependencies(graph: DefectKnowledgeGraph, project_root: Path) -> None:
    component_nodes = graph.get_nodes_by_type("Component")
    comp_paths = {
        attrs["file_path"] if "file_path" in attrs else node_id.removeprefix("comp:")
        for node_id, attrs in component_nodes
    }

    module_lookup = _build_module_lookup(project_root)

    for comp_path in comp_paths:
        abs_path = project_root / comp_path
        if not abs_path.exists():
            continue

        try:
            source = abs_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            imported_module = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_module = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_module = node.module

            if imported_module is None:
                continue

            resolved_path = module_lookup.get(imported_module)
            if resolved_path and resolved_path in comp_paths and resolved_path != comp_path:
                graph.add_edge(f"comp:{comp_path}", f"comp:{resolved_path}", "DEPENDS_ON")


def build_from_generated_tests(
    graph: DefectKnowledgeGraph,
    tests: list[GeneratedTest],
    test_type: str,
) -> None:
    component_nodes = graph.get_nodes_by_type("Component")
    name_to_id = {attrs["name"]: nid for nid, attrs in component_nodes}

    for test in tests:
        test_path = f"tests/{test.file_name}"
        graph.add_node(
            f"test:{test_path}",
            "TestFile",
            file_path=test_path,
            test_type=test_type,
        )

        comp_id = name_to_id.get(test.target_component)
        if comp_id:
            graph.add_edge(f"test:{test_path}", comp_id, "COVERS")


def build_from_anomalies(
    graph: DefectKnowledgeGraph,
    anomaly_reports: list[StructuredAnomalyReport],
) -> None:
    for anomaly in anomaly_reports:
        error_type = _extract_error_type(anomaly.correlated_stack_trace)
        pattern_key = f"{error_type}::{anomaly.affected_component}::{anomaly.classification}"

        graph.add_node(
            f"defect:{anomaly.anomaly_id}",
            "Defect",
            anomaly_id=anomaly.anomaly_id,
            classification=anomaly.classification,
            root_cause=anomaly.root_cause_hypothesis,
            error_type=error_type,
            pattern_key=pattern_key,
        )

        comp_id = f"comp:{anomaly.affected_component}"
        if graph.get_node(comp_id):
            graph.add_edge(f"defect:{anomaly.anomaly_id}", comp_id, "AFFECTS")

        test_id = f"test:{anomaly.test_id}"
        if graph.get_node(test_id):
            graph.add_edge(f"defect:{anomaly.anomaly_id}", test_id, "DETECTED_BY")

        existing_defects = graph.get_nodes_by_type("Defect")
        for existing_id, existing_attrs in existing_defects:
            if existing_id == f"defect:{anomaly.anomaly_id}":
                continue
            if existing_attrs.get("pattern_key") == pattern_key:
                graph.add_edge(f"defect:{anomaly.anomaly_id}", existing_id, "HAS_PATTERN")


def build_from_healing(
    graph: DefectKnowledgeGraph,
    healing_actions: list[HealingAction],
) -> None:
    for action in healing_actions:
        graph.add_node(
            f"heal:{action.anomaly_id}",
            "HealingAction",
            anomaly_id=action.anomaly_id,
            action_type=action.action_type,
            success=action.success,
            explanation=action.explanation,
        )

        defect_id = f"defect:{action.anomaly_id}"
        if graph.get_node(defect_id):
            graph.add_edge(f"heal:{action.anomaly_id}", defect_id, "FIXES")

        if action.target_file:
            target_id = None
            if action.target_file.startswith("tests/"):
                candidate = f"test:{action.target_file}"
                if graph.get_node(candidate):
                    target_id = candidate
            else:
                candidate = f"comp:{action.target_file}"
                if graph.get_node(candidate):
                    target_id = candidate

            if target_id:
                graph.add_edge(f"heal:{action.anomaly_id}", target_id, "MODIFIES")


def _build_module_lookup(project_root: Path) -> dict[str, str]:
    lookup = {}
    for py_file in project_root.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        rel = py_file.relative_to(project_root)
        rel_posix = rel.as_posix()
        dotted = rel_posix.replace("/", ".").removesuffix(".py")
        lookup[dotted] = rel_posix
    return lookup


def _extract_error_type(stack_trace: str) -> str:
    for line in reversed(stack_trace.strip().splitlines()):
        line = line.strip()
        if ":" in line and not line.startswith("File"):
            return line.split(":")[0].strip()
    return "UnknownError"
