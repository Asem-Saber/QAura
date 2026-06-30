import json
from pathlib import Path
from collections import deque

import networkx as nx
from networkx.readwrite import json_graph


class DefectKnowledgeGraph:
    """Thin wrapper around networkx.DiGraph with JSON persistence."""

    def __init__(self):
        self.graph = nx.DiGraph()

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.graph = json_graph.node_link_graph(data, directed=True, edges="links")

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json_graph.node_link_data(self.graph, edges="links")
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def add_node(self, node_id: str, node_type: str, **properties) -> None:
        if self.graph.has_node(node_id):
            self.graph.nodes[node_id].update(properties)
            self.graph.nodes[node_id]["node_type"] = node_type
        else:
            self.graph.add_node(node_id, node_type=node_type, **properties)

    def get_node(self, node_id: str) -> dict | None:
        if not self.graph.has_node(node_id):
            return None
        return dict(self.graph.nodes[node_id])

    def get_nodes_by_type(self, node_type: str) -> list[tuple[str, dict]]:
        return [
            (nid, dict(attrs))
            for nid, attrs in self.graph.nodes(data=True)
            if attrs.get("node_type") == node_type
        ]

    def add_edge(self, source: str, target: str, relation: str, **properties) -> None:
        self.graph.add_edge(source, target, relation=relation, **properties)

    def get_neighbors(
        self,
        node_id: str,
        relation: str | None = None,
        direction: str = "outgoing",
    ) -> list[tuple[str, dict]]:
        if not self.graph.has_node(node_id):
            return []

        results = []
        if direction in ("outgoing", "both"):
            for _, target, edge_data in self.graph.out_edges(node_id, data=True):
                if relation is None or edge_data.get("relation") == relation:
                    results.append((target, dict(self.graph.nodes[target])))

        if direction in ("incoming", "both"):
            for source, _, edge_data in self.graph.in_edges(node_id, data=True):
                if relation is None or edge_data.get("relation") == relation:
                    results.append((source, dict(self.graph.nodes[source])))

        return results

    def get_all_reachable(
        self,
        node_id: str,
        relation: str,
        direction: str = "outgoing",
        max_depth: int = 10,
    ) -> list[str]:
        if not self.graph.has_node(node_id):
            return []

        visited = set()
        queue = deque([(node_id, 0)])
        result = []

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue

            neighbors = self.get_neighbors(current, relation=relation, direction=direction)
            for neighbor_id, _ in neighbors:
                if neighbor_id not in visited and neighbor_id != node_id:
                    visited.add(neighbor_id)
                    result.append(neighbor_id)
                    queue.append((neighbor_id, depth + 1))

        return result
