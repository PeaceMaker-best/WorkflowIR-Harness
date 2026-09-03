from __future__ import annotations

import ast
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


PLACEHOLDER_RE = re.compile(r"\{\{#([^.{}]+)\.([^#{}]+)#\}\}")
SELECTOR_KEYS = {
    "value_selector",
    "variable_selector",
    "query_variable_selector",
    "iterator_selector",
    "output_selector",
}
PLATFORM_SOURCES = {"sys", "env", "conversation", "user"}


@dataclass(frozen=True)
class DifyDslValidationError:
    layer: str
    code: str
    message: str
    node_id: Optional[str] = None
    path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _walk(value: Any, path: str = "") -> Iterable[Tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, str(key), child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, "", child
            yield from _walk(child, child_path)


def _selector_source(value: Any) -> Optional[str]:
    if not isinstance(value, list) or len(value) < 2:
        return None
    if not all(isinstance(part, (str, int)) for part in value[:2]):
        return None
    return str(value[0])


def _reachable(seeds: Iterable[str], adjacency: Dict[str, Set[str]]) -> Set[str]:
    visited: Set[str] = set()
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        queue.extend(adjacency.get(current, set()) - visited)
    return visited


def validate_dify_dsl(document: Any) -> List[DifyDslValidationError]:
    """Validate the exact Dify document that will be submitted to the import API."""
    errors: List[DifyDslValidationError] = []
    if not isinstance(document, dict):
        return [
            DifyDslValidationError(
                "format", "DSL_NOT_OBJECT", "Dify DSL must be a mapping", path="$"
            )
        ]

    workflow = document.get("workflow")
    graph = workflow.get("graph") if isinstance(workflow, dict) else None
    if not isinstance(graph, dict):
        return [
            DifyDslValidationError(
                "format",
                "GRAPH_NOT_OBJECT",
                "workflow.graph must be a mapping",
                path="workflow.graph",
            )
        ]

    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list):
        errors.append(
            DifyDslValidationError(
                "format", "NODES_NOT_LIST", "workflow.graph.nodes must be a list", path="workflow.graph.nodes"
            )
        )
        nodes = []
    if not isinstance(edges, list):
        errors.append(
            DifyDslValidationError(
                "format", "EDGES_NOT_LIST", "workflow.graph.edges must be a list", path="workflow.graph.edges"
            )
        )
        edges = []

    node_by_id: Dict[str, Dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        path = f"workflow.graph.nodes[{index}]"
        if not isinstance(node, dict):
            errors.append(DifyDslValidationError("format", "NODE_NOT_OBJECT", "Node must be a mapping", path=path))
            continue
        node_id = str(node.get("id") or "")
        if not node_id:
            errors.append(DifyDslValidationError("graph", "NODE_ID_MISSING", "Node id is required", path=f"{path}.id"))
            continue
        if node_id in node_by_id:
            errors.append(
                DifyDslValidationError(
                    "graph", "DUPLICATE_NODE_ID", f"Duplicate node id {node_id}", node_id=node_id, path=f"{path}.id"
                )
            )
        node_by_id[node_id] = node
        node_data = node.get("data")
        if not isinstance(node_data, dict) or not str(node_data.get("type") or ""):
            errors.append(
                DifyDslValidationError(
                    "format", "NODE_TYPE_MISSING", "Node data.type is required", node_id=node_id, path=f"{path}.data.type"
                )
            )

    node_ids: Set[str] = set(node_by_id)
    iteration_owner: Dict[str, str] = {}
    for node_id, node in node_by_id.items():
        node_data = node.get("data") or {}
        raw_owner = node.get("parentId")
        if raw_owner is None and node_data.get("isInIteration"):
            raw_owner = node_data.get("iteration_id")
        if raw_owner is not None:
            iteration_owner[node_id] = str(raw_owner)

    iteration_ids = {
        node_id
        for node_id, node in node_by_id.items()
        if (node.get("data") or {}).get("type") == "iteration"
    }
    iteration_children: Dict[str, Set[str]] = defaultdict(set)
    for child_id, owner_id in iteration_owner.items():
        iteration_children[owner_id].add(child_id)

    top_node_ids = node_ids - set(iteration_owner)
    starts = [
        node_id
        for node_id in top_node_ids
        if (node_by_id[node_id].get("data") or {}).get("type") == "start"
    ]
    ends = [
        node_id
        for node_id in top_node_ids
        if (node_by_id[node_id].get("data") or {}).get("type") == "end"
    ]
    if len(starts) != 1:
        errors.append(
            DifyDslValidationError("graph", "START_COUNT_INVALID", f"Expected exactly one start node, got {len(starts)}")
        )
    if not ends:
        errors.append(DifyDslValidationError("graph", "END_MISSING", "Workflow has no end node"))

    top_adjacency: Dict[str, Set[str]] = defaultdict(set)
    top_reverse: Dict[str, Set[str]] = defaultdict(set)
    internal_adjacency: Dict[str, Set[str]] = defaultdict(set)
    internal_reverse: Dict[str, Set[str]] = defaultdict(set)
    for index, edge in enumerate(edges):
        path = f"workflow.graph.edges[{index}]"
        if not isinstance(edge, dict):
            errors.append(DifyDslValidationError("format", "EDGE_NOT_OBJECT", "Edge must be a mapping", path=path))
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_ids:
            errors.append(
                DifyDslValidationError("graph", "EDGE_SOURCE_NOT_FOUND", f"Unknown edge source {source}", path=f"{path}.source")
            )
        if target not in node_ids:
            errors.append(
                DifyDslValidationError("graph", "EDGE_TARGET_NOT_FOUND", f"Unknown edge target {target}", path=f"{path}.target")
            )
        if source and target and source == target:
            errors.append(DifyDslValidationError("graph", "SELF_LOOP", f"Self-loop on node {source}", node_id=source, path=path))
        if edge.get("sourceHandle") in {None, ""}:
            errors.append(DifyDslValidationError("graph", "SOURCE_HANDLE_MISSING", "Edge sourceHandle is required", path=f"{path}.sourceHandle"))
        if edge.get("targetHandle") in {None, ""}:
            errors.append(DifyDslValidationError("graph", "TARGET_HANDLE_MISSING", "Edge targetHandle is required", path=f"{path}.targetHandle"))
        if source in node_ids and target in node_ids:
            source_scope = iteration_owner.get(source)
            target_scope = iteration_owner.get(target)
            if source_scope != target_scope:
                errors.append(
                    DifyDslValidationError(
                        "graph",
                        "ITERATION_EDGE_CROSSES_SCOPE",
                        f"Edge {source} -> {target} crosses iteration scopes",
                        path=path,
                    )
                )
            elif source_scope is None:
                top_adjacency[source].add(target)
                top_reverse[target].add(source)
            else:
                internal_adjacency[source].add(target)
                internal_reverse[target].add(source)

    indegree = {node_id: 0 for node_id in top_node_ids}
    for source, targets in top_adjacency.items():
        for target in targets:
            if source in top_node_ids and target in top_node_ids:
                indegree[target] += 1
    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for target in top_adjacency.get(current, set()):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if top_node_ids and visited != len(top_node_ids):
        errors.append(
            DifyDslValidationError(
                "graph",
                "TOP_LEVEL_CYCLE_DETECTED",
                "Top-level workflow graph contains a cycle",
            )
        )

    if len(starts) == 1:
        reachable_from_start = _reachable(starts, top_adjacency)
        for node_id in sorted(top_node_ids - reachable_from_start):
            errors.append(
                DifyDslValidationError(
                    "graph",
                    "TOP_LEVEL_NODE_UNREACHABLE_FROM_START",
                    f"Top-level node {node_id} is not reachable from start node {starts[0]}",
                    node_id=node_id,
                )
            )
    if ends:
        can_reach_end = _reachable(ends, top_reverse)
        for node_id in sorted(top_node_ids - can_reach_end):
            errors.append(
                DifyDslValidationError(
                    "graph",
                    "TOP_LEVEL_NODE_CANNOT_REACH_END",
                    f"Top-level node {node_id} cannot reach an end node",
                    node_id=node_id,
                )
            )

    for iteration_id in sorted(iteration_ids):
        children = iteration_children.get(iteration_id, set())
        iteration_starts = [
            child_id
            for child_id in children
            if (node_by_id[child_id].get("data") or {}).get("type")
            == "iteration-start"
        ]
        if len(iteration_starts) != 1:
            errors.append(
                DifyDslValidationError(
                    "graph",
                    "ITERATION_START_COUNT_INVALID",
                    f"Iteration {iteration_id} must have exactly one iteration-start node, got {len(iteration_starts)}",
                    node_id=iteration_id,
                )
            )

        indegree = {child_id: 0 for child_id in children}
        for source in children:
            for target in internal_adjacency.get(source, set()):
                if target in children:
                    indegree[target] += 1
        queue = deque(
            child_id for child_id, degree in indegree.items() if degree == 0
        )
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for target in internal_adjacency.get(current, set()):
                if target not in indegree:
                    continue
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if children and visited != len(children):
            errors.append(
                DifyDslValidationError(
                    "graph",
                    "ITERATION_CYCLE_DETECTED",
                    f"Iteration {iteration_id} contains an internal cycle",
                    node_id=iteration_id,
                )
            )

        if len(iteration_starts) == 1:
            reachable_from_iteration_start = _reachable(
                iteration_starts, internal_adjacency
            )
            for child_id in sorted(children - reachable_from_iteration_start):
                errors.append(
                    DifyDslValidationError(
                        "graph",
                        "ITERATION_NODE_UNREACHABLE_FROM_START",
                        f"Iteration node {child_id} is not reachable from {iteration_starts[0]}",
                        node_id=child_id,
                    )
                )

        iteration_data = node_by_id[iteration_id].get("data") or {}
        output_source = _selector_source(iteration_data.get("output_selector"))
        if output_source not in children:
            errors.append(
                DifyDslValidationError(
                    "binding",
                    "ITERATION_OUTPUT_SOURCE_INVALID",
                    f"Iteration {iteration_id} output_selector must reference a node in its own scope",
                    node_id=iteration_id,
                    path=f"node[{iteration_id}].data.output_selector",
                )
            )
        else:
            can_reach_output = _reachable([output_source], internal_reverse)
            for child_id in sorted(children - can_reach_output):
                errors.append(
                    DifyDslValidationError(
                        "graph",
                        "ITERATION_NODE_CANNOT_REACH_OUTPUT",
                        f"Iteration node {child_id} cannot reach output node {output_source}",
                        node_id=child_id,
                    )
                )

    top_ancestor_cache: Dict[str, Set[str]] = {}
    internal_ancestor_cache: Dict[str, Set[str]] = {}

    def top_ancestors(node_id: str) -> Set[str]:
        if node_id not in top_ancestor_cache:
            top_ancestor_cache[node_id] = _reachable([node_id], top_reverse) - {
                node_id
            }
        return top_ancestor_cache[node_id]

    def internal_ancestors(node_id: str) -> Set[str]:
        if node_id not in internal_ancestor_cache:
            internal_ancestor_cache[node_id] = _reachable(
                [node_id], internal_reverse
            ) - {node_id}
        return internal_ancestor_cache[node_id]

    def is_visible_upstream(source: str, target: str) -> bool:
        """Resolve strict upstream visibility through nested iteration scopes."""
        current = target
        visited_scopes: Set[str] = set()
        while True:
            current_scope = iteration_owner.get(current)
            source_scope = iteration_owner.get(source)
            if source_scope == current_scope:
                ancestors = (
                    top_ancestors(current)
                    if current_scope is None
                    else internal_ancestors(current)
                )
                return source in ancestors
            if current_scope is None or current_scope in visited_scopes:
                return False
            if source == current_scope:
                return True
            visited_scopes.add(current_scope)
            current = current_scope

    def target_scope_lineage(target: str) -> Set[str]:
        lineage: Set[str] = set()
        current = iteration_owner.get(target)
        while current is not None and current not in lineage:
            lineage.add(current)
            current = iteration_owner.get(current)
        return lineage

    def validate_reference_scope(
        source: str,
        target: str,
        path: str,
        *,
        allow_iteration_output: bool = False,
    ) -> None:
        if source in PLATFORM_SOURCES or source not in node_ids:
            return
        source_owner = iteration_owner.get(source)
        target_owner = iteration_owner.get(target)
        if allow_iteration_output and source_owner == target:
            return
        if is_visible_upstream(source, target):
            return
        if (
            source_owner is not None
            and source_owner not in target_scope_lineage(target)
        ):
            errors.append(
                DifyDslValidationError(
                    "binding",
                    "SELECTOR_SOURCE_OUT_OF_SCOPE",
                    f"Iteration child {source} is not visible in the scope of {target}",
                    node_id=target,
                    path=path,
                )
            )
            return
        errors.append(
            DifyDslValidationError(
                "binding",
                "SELECTOR_SOURCE_NOT_UPSTREAM",
                f"Selector source {source} is not a strict upstream node of {target}",
                node_id=target,
                path=path,
            )
        )

    for node_id, node in node_by_id.items():
        node_data = node.get("data") or {}
        parent_id = iteration_owner.get(node_id)
        if parent_id is not None and parent_id not in node_ids:
            errors.append(
                DifyDslValidationError(
                    "graph",
                    "ITERATION_PARENT_NOT_FOUND",
                    f"Iteration parent {parent_id} does not exist",
                    node_id=node_id,
                    path="parentId",
                )
            )

        for path, key, value in _walk(node_data, f"node[{node_id}].data"):
            if key in SELECTOR_KEYS and value not in (None, []):
                source = _selector_source(value)
                if source is None:
                    errors.append(
                        DifyDslValidationError(
                            "binding",
                            "SELECTOR_SHAPE_INVALID",
                            f"{key} must be [source_node_id, variable_name]",
                            node_id=node_id,
                            path=path,
                        )
                    )
                elif source not in node_ids and source not in PLATFORM_SOURCES:
                    errors.append(
                        DifyDslValidationError(
                            "binding",
                            "SELECTOR_SOURCE_NOT_FOUND",
                            f"Selector source {source} does not exist",
                            node_id=node_id,
                            path=path,
                        )
                    )
                else:
                    validate_reference_scope(
                        source,
                        node_id,
                        path,
                        allow_iteration_output=(
                            key == "output_selector"
                            and node_data.get("type") == "iteration"
                            and iteration_owner.get(source) == node_id
                        ),
                    )
            if isinstance(value, str):
                for source, _ in PLACEHOLDER_RE.findall(value):
                    if source not in node_ids and source not in PLATFORM_SOURCES:
                        errors.append(
                            DifyDslValidationError(
                                "binding",
                                "PLACEHOLDER_SOURCE_NOT_FOUND",
                                f"Placeholder source {source} does not exist",
                                node_id=node_id,
                                path=path,
                            )
                        )
                    else:
                        validate_reference_scope(source, node_id, path)

        if node_data.get("type") == "code" and str(node_data.get("code_language") or "python3") == "python3":
            code = node_data.get("code")
            if isinstance(code, str) and code.strip():
                try:
                    ast.parse(code)
                except SyntaxError as exc:
                    errors.append(
                        DifyDslValidationError(
                            "binding",
                            "PYTHON_SYNTAX_INVALID",
                            f"Python syntax error at line {exc.lineno}: {exc.msg}",
                            node_id=node_id,
                            path="data.code",
                        )
                    )

    deduplicated: List[DifyDslValidationError] = []
    seen: Set[Tuple[Any, ...]] = set()
    for error in errors:
        key = (error.layer, error.code, error.message, error.node_id, error.path)
        if key not in seen:
            seen.add(key)
            deduplicated.append(error)
    return deduplicated
