import json
import tempfile
from pathlib import Path

from knowledge_graph.graph_store import DefectKnowledgeGraph


def test_add_and_get_node():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:demo_app/auth.py", "Component", file_path="demo_app/auth.py", name="Auth")
    node = kg.get_node("comp:demo_app/auth.py")
    assert node is not None
    assert node["node_type"] == "Component"
    assert node["file_path"] == "demo_app/auth.py"
    assert node["name"] == "Auth"


def test_get_node_returns_none_for_missing():
    kg = DefectKnowledgeGraph()
    assert kg.get_node("comp:nonexistent.py") is None


def test_add_node_is_idempotent_upsert():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:auth.py", "Component", name="Auth")
    kg.add_node("comp:auth.py", "Component", version="2")
    node = kg.get_node("comp:auth.py")
    assert node["name"] == "Auth"
    assert node["version"] == "2"
    assert node["node_type"] == "Component"


def test_get_nodes_by_type():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:a.py", "Component", name="A")
    kg.add_node("comp:b.py", "Component", name="B")
    kg.add_node("risk:sql", "RiskArea", name="SQL injection")
    components = kg.get_nodes_by_type("Component")
    assert len(components) == 2
    ids = [nid for nid, _ in components]
    assert "comp:a.py" in ids
    assert "comp:b.py" in ids


def test_add_and_get_edge():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:a.py", "Component")
    kg.add_node("comp:b.py", "Component")
    kg.add_edge("comp:a.py", "comp:b.py", "DEPENDS_ON")
    neighbors = kg.get_neighbors("comp:a.py", relation="DEPENDS_ON", direction="outgoing")
    assert len(neighbors) == 1
    assert neighbors[0][0] == "comp:b.py"


def test_get_neighbors_incoming():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:a.py", "Component")
    kg.add_node("comp:b.py", "Component")
    kg.add_edge("comp:a.py", "comp:b.py", "DEPENDS_ON")
    neighbors = kg.get_neighbors("comp:b.py", relation="DEPENDS_ON", direction="incoming")
    assert len(neighbors) == 1
    assert neighbors[0][0] == "comp:a.py"


def test_get_neighbors_filters_by_relation():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:a.py", "Component")
    kg.add_node("comp:b.py", "Component")
    kg.add_node("risk:sql", "RiskArea")
    kg.add_edge("comp:a.py", "comp:b.py", "DEPENDS_ON")
    kg.add_edge("comp:a.py", "risk:sql", "BELONGS_TO")
    deps = kg.get_neighbors("comp:a.py", relation="DEPENDS_ON", direction="outgoing")
    assert len(deps) == 1
    assert deps[0][0] == "comp:b.py"


def test_get_all_reachable_bfs():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:a.py", "Component")
    kg.add_node("comp:b.py", "Component")
    kg.add_node("comp:c.py", "Component")
    kg.add_edge("comp:a.py", "comp:b.py", "DEPENDS_ON")
    kg.add_edge("comp:b.py", "comp:c.py", "DEPENDS_ON")
    reachable = kg.get_all_reachable("comp:a.py", "DEPENDS_ON", direction="outgoing")
    assert set(reachable) == {"comp:b.py", "comp:c.py"}


def test_get_all_reachable_respects_max_depth():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:a.py", "Component")
    kg.add_node("comp:b.py", "Component")
    kg.add_node("comp:c.py", "Component")
    kg.add_edge("comp:a.py", "comp:b.py", "DEPENDS_ON")
    kg.add_edge("comp:b.py", "comp:c.py", "DEPENDS_ON")
    reachable = kg.get_all_reachable("comp:a.py", "DEPENDS_ON", direction="outgoing", max_depth=1)
    assert reachable == ["comp:b.py"]


def test_save_and_load_roundtrip():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:auth.py", "Component", name="Auth")
    kg.add_node("comp:orders.py", "Component", name="Orders")
    kg.add_edge("comp:orders.py", "comp:auth.py", "DEPENDS_ON")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "graph.json"
        kg.save(path)

        assert path.exists()
        data = json.loads(path.read_text())
        assert "nodes" in data
        assert "links" in data

        kg2 = DefectKnowledgeGraph()
        kg2.load(path)
        node = kg2.get_node("comp:auth.py")
        assert node is not None
        assert node["name"] == "Auth"
        neighbors = kg2.get_neighbors("comp:orders.py", relation="DEPENDS_ON", direction="outgoing")
        assert len(neighbors) == 1


def test_load_missing_file_starts_empty():
    kg = DefectKnowledgeGraph()
    kg.load(Path("/nonexistent/path/graph.json"))
    assert kg.get_nodes_by_type("Component") == []


def test_add_edge_is_idempotent():
    kg = DefectKnowledgeGraph()
    kg.add_node("comp:a.py", "Component")
    kg.add_node("comp:b.py", "Component")
    kg.add_edge("comp:a.py", "comp:b.py", "DEPENDS_ON")
    kg.add_edge("comp:a.py", "comp:b.py", "DEPENDS_ON")
    neighbors = kg.get_neighbors("comp:a.py", relation="DEPENDS_ON", direction="outgoing")
    assert len(neighbors) == 1
