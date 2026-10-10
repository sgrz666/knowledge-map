"""NetworkX view over the library graphs, with the edge vocabulary as a runtime contract.

``docs/agent_architecture.md`` §3.1 makes the 16 edge names a hard whitelist: a 17th name in
``edges.jsonl`` raises instead of being silently tolerated, because the two-tier trust model
assumes the vocabulary is closed and reviewed.

Edge orientation is fixed by the data (verified against both libraries on 2026-10-10):

    assesses                 knowledge node -> question
    supports_ability         ability node   -> question / resource
    aligned_to_requirement   L0 clause      -> node / question
    has_rubric               question       -> rubric
    refers_to_material       question       -> material
    contains / has_child / comprises / specifies / targets / basis   parent -> child
    confused_with / misconception_lead_to / prerequisite_of          node -> node
    supports_resource / supplements_resource                          node -> resource

So "which nodes does this question test" is an *inbound* ``assesses`` lookup, not an outbound
one. Getting that backwards silently yields empty evidence everywhere, which is why the
helpers below encode the direction once and the tests assert it against real ids.

Edge review state (``verified`` / ``mapping_status`` / ``active_for_learning_path``) is passed
through unchanged — nothing here upgrades it, which is what keeps the 0 confirmed prerequisite
edges out of the planner.
"""
from __future__ import annotations

import threading
from functools import lru_cache
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import networkx as nx

from services.knowledge.repository import KnowledgeRepository, get_repository

# Closed vocabulary from the design document §3.4. Adding a name here is a data-contract
# decision for the 教研 reviewer, never a runtime convenience.
ALLOWED_EDGE_TYPES: Tuple[str, ...] = (
    "specifies",
    "contains",
    "targets",
    "supports_ability",
    "has_rubric",
    "refers_to_material",
    "has_child",
    "assesses",
    "prerequisite_of",
    "comprises",
    "basis",
    "aligned_to_requirement",
    "confused_with",
    "misconception_lead_to",
    "supports_resource",
    "supplements_resource",
)
ALLOWED_EDGE_TYPES_SET = frozenset(ALLOWED_EDGE_TYPES)

CONTAINER_EDGES = ("contains", "comprises", "has_child", "specifies", "targets", "basis")
MISCONCEPTION_EDGES = ("confused_with", "misconception_lead_to")
RESOURCE_EDGES = ("supports_resource", "supplements_resource")

PREREQUISITE_DISABLED_NOTICE = (
    "先修边未启用：库内 prerequisite_of 全部 active_for_learning_path=false（0 条经教研核定），"
    "路径排序不含前置阻断保证。"
)
UNREVIEWED_MAPPING_NOTICE = (
    "图谱挂载为自动生成（mapping_status=automatic_pending_review / tagger），未经教研核对，"
    "只可作检索线索，不可作为能力断定依据。"
)

LIBRARY_VALUES = ("ntce", "cet")


class UnknownEdgeTypeError(RuntimeError):
    """Raised when edges.jsonl carries an edge name outside the closed vocabulary."""


class GraphIndex:
    """Read-only multigraph for one library, built once per process."""

    def __init__(self, library: str, repository: Optional[KnowledgeRepository] = None) -> None:
        if library not in LIBRARY_VALUES:
            raise ValueError(f"unknown library: {library} (expected one of {LIBRARY_VALUES})")
        self.library = library
        self.repository = repository or get_repository()
        self._lock = threading.Lock()
        self._graph: Optional[nx.MultiDiGraph] = None
        self._edge_stats: Dict[str, dict] = {}
        self._node_meta: Dict[str, dict] = {}

    # ------------------------------------------------------------------ build
    @property
    def graph(self) -> nx.MultiDiGraph:
        if self._graph is None:
            with self._lock:
                if self._graph is None:
                    self._build()
        assert self._graph is not None
        return self._graph

    def _build(self) -> None:
        nodes, edges = self.repository.graph_records(self.library)
        graph = nx.MultiDiGraph()
        for record in nodes:
            nid = record.get("id")
            if nid:
                self._node_meta[nid] = record
                graph.add_node(nid, layer=record.get("layer"), type=record.get("type"), name=record.get("name"))

        stats: Dict[str, dict] = {}
        for record in edges:
            edge_type = record.get("type")
            if edge_type not in ALLOWED_EDGE_TYPES_SET:
                raise UnknownEdgeTypeError(
                    f"{self.library}: edge type {edge_type!r} is outside the closed 16-name vocabulary; "
                    "the data contract must be reviewed before the runtime accepts it."
                )
            src, dst = record.get("src"), record.get("dst")
            if not src or not dst:
                continue
            graph.add_edge(
                src,
                dst,
                key=edge_type,
                verified=record.get("verified"),
                mapping_status=record.get("mapping_status"),
                active_for_learning_path=record.get("active_for_learning_path"),
                status=record.get("status"),
            )
            row = stats.setdefault(
                str(edge_type), {"total": 0, "verified": 0, "unverified": 0, "active_for_learning_path": 0}
            )
            row["total"] += 1
            row["verified" if record.get("verified") else "unverified"] += 1
            if record.get("active_for_learning_path"):
                row["active_for_learning_path"] += 1
        self._edge_stats = stats
        self._graph = graph

    # ------------------------------------------------------------------ lookup
    def node(self, node_id: str) -> Optional[dict]:
        self.graph
        return self._node_meta.get(node_id)

    def nodes_of_layer(self, layer: str) -> Iterator[str]:
        self.graph
        for nid, record in self._node_meta.items():
            if record.get("layer") == layer:
                yield nid

    def link_out(self, node_id: str, *edge_types: str) -> List[Tuple[str, dict]]:
        """Neighbours this node points at, with the edge attributes."""
        return self._linked(node_id, edge_types, reverse=False)

    def link_in(self, node_id: str, *edge_types: str) -> List[Tuple[str, dict]]:
        """Neighbours pointing at this node, with the edge attributes."""
        return self._linked(node_id, edge_types, reverse=True)

    def _linked(self, node_id: str, edge_types: Sequence[str], *, reverse: bool) -> List[Tuple[str, dict]]:
        graph = self.graph
        if node_id not in graph:
            return []
        wanted = set(edge_types)
        out: List[Tuple[str, dict]] = []
        seen: set = set()
        if reverse:
            pairs = ((src, graph.succ[src].get(node_id, {})) for src in graph.pred[node_id])
        else:
            pairs = ((dst, graph.succ[node_id][dst]) for dst in graph.succ[node_id])
        for neighbour, parallel in pairs:
            for edge_type, attrs in parallel.items():
                if edge_type in wanted and (neighbour, edge_type) not in seen:
                    seen.add((neighbour, edge_type))
                    out.append((neighbour, dict(attrs or {}, edge_type=edge_type)))
        return out

    # -------------------------------------------------------- semantic queries
    def nodes_for_question(self, question_id: str) -> List[str]:
        """Knowledge nodes testing a question (``assesses`` points node -> question)."""
        return [src for src, _ in self.link_in(question_id, "assesses")]

    def questions_for_node(self, node_id: str) -> List[str]:
        return [dst for dst, _ in self.link_out(node_id, "assesses")]

    def abilities_for_question(self, question_id: str) -> List[str]:
        return [src for src, _ in self.link_in(question_id, "supports_ability")]

    def abilities_for_node(self, ability_node: str) -> List[str]:
        return [dst for dst, _ in self.link_out(ability_node, "supports_ability")]

    def requirements_for(self, node_id: str) -> List[str]:
        """L0 clauses aligned to a node or question (points clause -> target)."""
        return [src for src, _ in self.link_in(node_id, "aligned_to_requirement")]

    def requirements_for_question(self, question_id: str) -> List[str]:
        out = self.requirements_for(question_id)
        for nid in self.nodes_for_question(question_id):
            for rid in self.requirements_for(nid):
                if rid not in out:
                    out.append(rid)
        return out

    def rubric_for(self, node_id: str) -> List[str]:
        return [dst for dst, _ in self.link_out(node_id, "has_rubric")]

    def materials_for(self, question_id: str) -> List[str]:
        return [dst for dst, _ in self.link_out(question_id, "refers_to_material")]

    def misconceptions_for(self, node_id: str) -> List[Tuple[str, dict]]:
        return self.link_out(node_id, *MISCONCEPTION_EDGES) + self.link_in(node_id, *MISCONCEPTION_EDGES)

    def resources_for(self, node_id: str) -> List[str]:
        return [dst for dst, _ in self.link_out(node_id, *RESOURCE_EDGES)]

    def children_of(self, node_id: str) -> List[str]:
        return [dst for dst, _ in self.link_out(node_id, *CONTAINER_EDGES)]

    def parents_of(self, node_id: str) -> List[str]:
        return [src for src, _ in self.link_in(node_id, *CONTAINER_EDGES)]

    def module_of(self, node_id: str) -> Optional[str]:
        for parent in self.parents_of(node_id):
            if (self.node(parent) or {}).get("layer") in ("L1", "L2"):
                return parent
        return None

    # ------------------------------------------------------------- prerequisites
    def prerequisite_pairs(self) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        for src, dst, key, attrs in self.graph.edges(keys=True, data=True):
            if key == "prerequisite_of" and (attrs or {}).get("active_for_learning_path"):
                out.append((src, dst))
        return out

    @property
    def prerequisites_active(self) -> bool:
        """False while no prerequisite edge is confirmed — the planner must honour this."""
        return bool(self.prerequisite_pairs())

    def topological_order(self, node_ids: Iterable[str]) -> Tuple[List[str], str]:
        wanted = [n for n in node_ids if n in self.graph]
        rest = [n for n in node_ids if n not in self.graph]
        if not self.prerequisites_active:
            return wanted + rest, PREREQUISITE_DISABLED_NOTICE
        active = set(wanted) | {n for pair in self.prerequisite_pairs() for n in pair}
        sub = self.graph.subgraph(active)
        try:
            order = [n for n in nx.topological_sort(sub) if n in set(wanted)]
        except nx.NetworkXUnfeasible:
            return wanted + rest, "先修图存在环，已退回请求顺序。"
        return order + rest, ""

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        graph = self.graph
        return {
            "library": self.library,
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "edge_types": sorted(self._edge_stats),
            "edge_status": dict(self._edge_stats),
            "prerequisites_active_for_learning_path": self.prerequisites_active,
            "allowed_edge_types": list(ALLOWED_EDGE_TYPES),
        }

    def edge_labels(self) -> List[str]:
        self.graph
        labels: List[str] = []
        for name, row in sorted(self._edge_stats.items()):
            if name == "prerequisite_of":
                labels.append(f"prerequisite_of: {row['active_for_learning_path']}/{row['total']} 已核定入路径")
            else:
                labels.append(f"{name}: {row['verified']}/{row['total']} 边已核对")
        return labels

    def notices(self) -> List[str]:
        """Graph-level caveats any response built on this index must carry."""
        self.graph
        unmapped = [name for name, row in self._edge_stats.items() if row["total"] and not row["verified"]]
        out: List[str] = []
        if unmapped:
            out.append(UNREVIEWED_MAPPING_NOTICE + "（涉及边名：" + "、".join(sorted(unmapped)) + "）")
        if not self.prerequisites_active:
            out.append(PREREQUISITE_DISABLED_NOTICE)
        return out


@lru_cache(maxsize=4)
def get_graph_index(library: str) -> GraphIndex:
    return GraphIndex(library)


def library_for_exam(exam: Optional[str]) -> Optional[str]:
    if not exam:
        return None
    upper = exam.upper()
    if upper.startswith("NTCE") or upper == "省考":
        return "ntce"
    if upper.startswith("CET"):
        return "cet"
    return None
