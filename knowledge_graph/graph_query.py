import json
from collections import Counter

from langchain_core.tools import tool
from knowledge_graph.graph_store import DefectKnowledgeGraph

_kg: DefectKnowledgeGraph | None = None


def set_graph(kg: DefectKnowledgeGraph) -> None:
    global _kg
    _kg = kg


def _get_kg() -> DefectKnowledgeGraph:
    if _kg is None:
        return DefectKnowledgeGraph()
    return _kg


@tool
def query_risk_propagation(component_path: str) -> str:
    """Find all components that depend on the given component (reverse dependency traversal).

    Use this to understand the blast radius when a component changes — which other
    components might break and should be included in test coverage.

    Args:
        component_path: Relative file path of the component (e.g. 'demo_app/auth.py').
    """
    kg = _get_kg()
    node_id = f"comp:{component_path}"

    dependents_ids = kg.get_all_reachable(node_id, "DEPENDS_ON", direction="incoming")
    dependents = [nid.removeprefix("comp:") for nid in dependents_ids]

    risk_neighbors = kg.get_neighbors(node_id, relation="BELONGS_TO", direction="outgoing")
    risk_areas = [attrs.get("name", nid) for nid, attrs in risk_neighbors]

    return json.dumps({
        "component": component_path,
        "dependents": dependents,
        "depth": len(dependents),
        "risk_areas": risk_areas,
    })


@tool
def query_similar_defects(error_type: str, component: str, classification: str) -> str:
    """Search the knowledge graph for past defects with the same pattern signature.

    Use this before investigating a failure from scratch — if the same error type
    occurred in the same component with the same classification before, reuse
    the prior diagnosis and healing strategy.

    Args:
        error_type: The exception type (e.g. 'AssertionError', 'TypeError').
        component: Relative file path of the affected component (e.g. 'demo_app/auth.py').
        classification: Defect classification ('INFRASTRUCTURE', 'APPLICATION_DEFECT', 'TEST_SCRIPT_DECAY').
    """
    kg = _get_kg()
    pattern_key = f"{error_type}::{component}::{classification}"

    matches = []
    for defect_id, defect_attrs in kg.get_nodes_by_type("Defect"):
        if defect_attrs.get("pattern_key") == pattern_key:
            healing_info = None
            heal_neighbors = kg.get_neighbors(defect_id, relation="FIXES", direction="incoming")
            for heal_id, heal_attrs in heal_neighbors:
                healing_info = {
                    "action_type": heal_attrs.get("action_type", ""),
                    "success": heal_attrs.get("success", False),
                    "explanation": heal_attrs.get("explanation", ""),
                }
                break

            matches.append({
                "anomaly_id": defect_attrs.get("anomaly_id", ""),
                "root_cause": defect_attrs.get("root_cause", ""),
                "healing": healing_info,
            })

    return json.dumps({
        "pattern_key": pattern_key,
        "matches": matches,
    })


@tool
def query_healing_patterns(defect_classification: str) -> str:
    """Find historically successful healing strategies for a given defect classification.

    Use this before attempting a fix — prioritize strategies that have worked
    before for this type of failure.

    Args:
        defect_classification: The defect classification (e.g. 'APPLICATION_DEFECT', 'INFRASTRUCTURE').
    """
    kg = _get_kg()

    success_counter: Counter = Counter()
    total_counter: Counter = Counter()

    for defect_id, defect_attrs in kg.get_nodes_by_type("Defect"):
        if defect_attrs.get("classification") != defect_classification:
            continue

        heal_neighbors = kg.get_neighbors(defect_id, relation="FIXES", direction="incoming")
        for _, heal_attrs in heal_neighbors:
            action_type = heal_attrs.get("action_type", "")
            total_counter[action_type] += 1
            if heal_attrs.get("success"):
                success_counter[action_type] += 1

    patterns = [
        {
            "action_type": action_type,
            "success_count": success_counter[action_type],
            "total_count": count,
        }
        for action_type, count in total_counter.most_common()
    ]

    return json.dumps({
        "classification": defect_classification,
        "patterns": patterns,
    })


@tool
def query_component_health(component_path: str) -> str:
    """Compute a health score for a component based on defect history, healing success, and test coverage.

    Use this to include per-component health metrics in the QA report.

    Args:
        component_path: Relative file path of the component (e.g. 'demo_app/auth.py').
    """
    kg = _get_kg()
    node_id = f"comp:{component_path}"

    if not kg.get_node(node_id):
        return json.dumps({
            "component": component_path,
            "defect_count": 0,
            "healing_success_rate": 0.0,
            "test_coverage_count": 0,
            "risk_areas": [],
            "health_score": 0.0,
        })

    defect_neighbors = kg.get_neighbors(node_id, relation="AFFECTS", direction="incoming")
    defect_count = len(defect_neighbors)

    heal_total = 0
    heal_success = 0
    for defect_id, _ in defect_neighbors:
        heal_neighbors = kg.get_neighbors(defect_id, relation="FIXES", direction="incoming")
        for _, heal_attrs in heal_neighbors:
            heal_total += 1
            if heal_attrs.get("success"):
                heal_success += 1

    healing_success_rate = heal_success / heal_total if heal_total > 0 else 0.0

    test_neighbors = kg.get_neighbors(node_id, relation="COVERS", direction="incoming")
    test_coverage_count = len(test_neighbors)

    risk_neighbors = kg.get_neighbors(node_id, relation="BELONGS_TO", direction="outgoing")
    risk_areas = [attrs.get("name", nid) for nid, attrs in risk_neighbors]

    health_score = (
        0.4 * healing_success_rate
        + 0.3 * min(test_coverage_count / 3, 1.0)
        + 0.3 * max(1.0 - defect_count / 10, 0.0)
    )

    return json.dumps({
        "component": component_path,
        "defect_count": defect_count,
        "healing_success_rate": round(healing_success_rate, 4),
        "test_coverage_count": test_coverage_count,
        "risk_areas": risk_areas,
        "health_score": round(health_score, 4),
    })
