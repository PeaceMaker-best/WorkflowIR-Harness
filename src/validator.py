from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


PLACEHOLDER_RE = re.compile(r"\{\{#['\"]?([^.'\"#]+)['\"]?\.([^#]+?)#\}\}")
DIFY_NODE_ID_RE = re.compile('^[1-9]\\d*(?:-[1-9]\\d*)?$')


@dataclass
class ValidationError:
    layer: str
    code: str
    message: str
    node_id: Optional[str] = None
    path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _walk(value: Any, path: str = "") -> Iterable[Tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _declared_outputs(node: Dict[str, Any]) -> Optional[Set[str]]:
    node_type = node.get("type")
    param = node.get("param") or {}
    fixed: Dict[str, Set[str]] = {
        "llm": {"text"},
        "question-classifier": {"class_name"},
        "document-extractor": {"text"},
        "http-request": {"body"},
        "list-operator": {"result", "first_record", "last_record"},
        "parameter-extractor": set(),
        "template-transform": {"output"},
        "variable-aggregator": {"output"},
        "iteration": {"output", "index", "item"},
        "tts": {"files"},
        "text2image": {"files"},
        "mermaid-converter": {"files"},
        "markdown-exporter": {"files"},
        "google-search": {"json"},
        "echarts": {"text"},
    }
    if node_type == "start":
        return {str(item[0]) for item in param.get("variables", []) if isinstance(item, list) and item}
    if node_type == "code":
        return {str(item[0]) for item in param.get("outputs", []) if isinstance(item, list) and item}
    if node_type == "parameter-extractor":
        return {str(item[1]) for item in param.get("parameters", []) if isinstance(item, list) and len(item) >= 2}
    return fixed.get(str(node_type))


def _required_params(schema_text: str) -> Set[str]:
    block = re.search(r"<parameter>(.*?)</parameter>", schema_text, re.S | re.I)
    if not block:
        return set()
    return set(re.findall(r"(?m)^\s*\d+\.\s*[\"“]([^\"”]+)[\"”]\s*:", block.group(1)))


def _reachable(seeds: Iterable[str], adjacency: Dict[str, Set[str]]) -> Set[str]:
    """Return every node reachable from ``seeds``, including the seeds."""
    visited: Set[str] = set()
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        queue.extend(adjacency.get(current, set()) - visited)
    return visited


def validate_workflow(
    workflow: Any,
    allowed_types: Set[str],
    schema_by_type: Dict[str, str],
) -> List[ValidationError]:
    errors: List[ValidationError] = []
    if not isinstance(workflow, dict):
        return [ValidationError("format", "WORKFLOW_NOT_OBJECT", "Workflow must be a JSON object")]
    nodes = workflow.get("nodes_info")
    edges = workflow.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return [
            ValidationError(
                "format",
                "MISSING_CORE_FIELDS",
                "nodes_info and edges must both be lists",
            )
        ]

    node_by_id: Dict[str, Dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(ValidationError("format", "NODE_NOT_OBJECT", f"Node {index} is not an object"))
            continue
        node_id = str(node.get("id", ""))
        node_type = str(node.get("type", ""))
        if not node_id:
            errors.append(ValidationError("format", "NODE_ID_MISSING", "Node id is missing", path=f"nodes_info[{index}].id"))
            continue
        if not DIFY_NODE_ID_RE.fullmatch(node_id):
            errors.append(
                ValidationError(
                    'adapter',
                    'DIFY_NODE_ID_INVALID',
                    f'Dify adapter requires numeric ids, got {node_id}',
                    node_id=node_id,
                    path=f'nodes_info[{index}].id',
                )
            )
        if node_id in node_by_id:
            errors.append(ValidationError("graph", "DUPLICATE_NODE_ID", f"Duplicate node id {node_id}", node_id=node_id))
        node_by_id[node_id] = node
        if node_type not in allowed_types:
            errors.append(ValidationError("consistency", "UNKNOWN_NODE_TYPE", f"Unknown node type {node_type}", node_id=node_id))
        if not isinstance(node.get("param"), dict):
            errors.append(ValidationError("format", "PARAM_NOT_OBJECT", "param must be an object", node_id=node_id))
            continue
        for required in _required_params(schema_by_type.get(node_type, "")):
            if required not in node["param"]:
                errors.append(
                    ValidationError(
                        "binding",
                        "REQUIRED_PARAM_MISSING",
                        f"Required parameter {required} is missing",
                        node_id=node_id,
                        path=f"param.{required}",
                    )
                )

    ids = set(node_by_id)
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    indegree: Dict[str, int] = {node_id: 0 for node_id in ids}
    degree: Dict[str, int] = {node_id: 0 for node_id in ids}
    for index, edge in enumerate(edges):
        if not isinstance(edge, list) or len(edge) != 3:
            errors.append(ValidationError("format", "EDGE_SHAPE_INVALID", "Edge must be [source, port, target]", path=f"edges[{index}]"))
            continue
        source, port, target = str(edge[0]), edge[1], str(edge[2])
        if source not in ids or target not in ids:
            errors.append(
                ValidationError(
                    "graph",
                    "EDGE_ENDPOINT_NOT_FOUND",
                    f"Edge endpoint is missing: {source} -> {target}",
                    path=f"edges[{index}]",
                )
            )
            continue
        if not isinstance(port, int) or port < 0:
            errors.append(ValidationError("graph", "EDGE_PORT_INVALID", f"Invalid output port {port}", path=f"edges[{index}][1]"))
        if target not in adjacency[source]:
            adjacency[source].add(target)
            indegree[target] += 1
        degree[source] += 1
        degree[target] += 1

    starts = [node_id for node_id, node in node_by_id.items() if node.get("type") == "start"]
    ends = [node_id for node_id, node in node_by_id.items() if node.get("type") == "end"]
    if not starts:
        errors.append(ValidationError("graph", "START_MISSING", "Workflow has no start node"))
    elif len(starts) > 1:
        errors.append(
            ValidationError(
                "graph",
                "MULTIPLE_START_NODES",
                f"Workflow must have exactly one start node, got {len(starts)}: {sorted(starts)}",
            )
        )
    if not ends:
        errors.append(ValidationError("graph", "END_MISSING", "Workflow has no end node"))
    for node_id, node in node_by_id.items():
        if degree.get(node_id, 0) == 0 and node.get("type") != "iteration-start":
            errors.append(ValidationError("graph", "ISOLATED_NODE", f"Node {node_id} is isolated", node_id=node_id))

    queue = deque([node_id for node_id, value in indegree.items() if value == 0])
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for target in adjacency.get(current, set()):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if ids and visited != len(ids):
        errors.append(ValidationError("graph", "CYCLE_DETECTED", "Workflow graph contains a cycle"))

    # Iteration children form a nested subgraph.  Represent the container's
    # enter/exit semantics as virtual edges for reachability and data-flow
    # validation without mutating the authored topology.
    execution_adjacency: Dict[str, Set[str]] = defaultdict(set)
    execution_reverse: Dict[str, Set[str]] = defaultdict(set)

    def add_execution_edge(source: str, target: str) -> None:
        if source in ids and target in ids and target not in execution_adjacency[source]:
            execution_adjacency[source].add(target)
            execution_reverse[target].add(source)

    for source, targets in adjacency.items():
        for target in targets:
            add_execution_edge(source, target)
    iteration_ids = {
        node_id
        for node_id, node in node_by_id.items()
        if node.get("type") == "iteration"
    }
    iteration_owner: Dict[str, str] = {}
    for child_id in ids:
        owners = [
            parent_id
            for parent_id in iteration_ids
            if child_id.startswith(f"{parent_id}-")
        ]
        if owners:
            iteration_owner[child_id] = max(owners, key=len)
    for parent_id, parent in node_by_id.items():
        if parent.get("type") != "iteration":
            continue
        internal_starts = [
            child_id
            for child_id, child in node_by_id.items()
            if child.get("type") == "iteration-start"
            and child_id.startswith(f"{parent_id}-")
        ]
        for child_id in internal_starts:
            add_execution_edge(parent_id, child_id)
        selector = (parent.get("param") or {}).get("output_selector")
        if isinstance(selector, list) and len(selector) == 2:
            output_source = str(selector[1])
            if output_source.startswith(f"{parent_id}-"):
                for outer_target in adjacency.get(parent_id, set()):
                    add_execution_edge(output_source, outer_target)

    # Degree and cycle checks alone accept disconnected components. Enforce
    # the executable workflow invariant: every node belongs to the one graph
    # entered through Start and can eventually terminate at an End node.
    if len(starts) == 1:
        reachable_from_start = _reachable(starts, execution_adjacency)
        for node_id in sorted(ids - reachable_from_start):
            errors.append(
                ValidationError(
                    "graph",
                    "NODE_UNREACHABLE_FROM_START",
                    f"Node {node_id} is not reachable from start node {starts[0]}",
                    node_id=node_id,
                )
            )
    if ends:
        can_reach_end = _reachable(ends, execution_reverse)
        for node_id in sorted(ids - can_reach_end):
            errors.append(
                ValidationError(
                    "graph",
                    "NODE_CANNOT_REACH_END",
                    f"Node {node_id} cannot reach any end node",
                    node_id=node_id,
                )
            )

    ancestor_cache: Dict[str, Set[str]] = {}

    def strict_ancestors(node_id: str) -> Set[str]:
        if node_id not in ancestor_cache:
            ancestor_cache[node_id] = _reachable([node_id], execution_reverse) - {node_id}
        return ancestor_cache[node_id]

    for node_id, node in node_by_id.items():
        param = node.get("param") or {}
        for path, value in _walk(param):
            references: List[Tuple[str, str]] = []
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and isinstance(value[1], (str, int))
                and re.fullmatch(r"\d+(?:-\d+)*", str(value[1]))
            ):
                variable_name, source_id = value[0], str(value[1])
                references.append((source_id, variable_name))
            if isinstance(value, str):
                references.extend((source_id, variable_name) for source_id, variable_name in PLACEHOLDER_RE.findall(value))
            for source_id, variable_name in references:
                if source_id not in ids:
                    errors.append(
                        ValidationError(
                            "binding",
                            "VARIABLE_SOURCE_NOT_FOUND",
                            f"Variable source node {source_id} does not exist",
                            node_id=node_id,
                            path=path,
                        )
                    )
                    continue
                declared = _declared_outputs(node_by_id[source_id])
                if declared is not None and variable_name not in declared:
                    errors.append(
                        ValidationError(
                            "binding",
                            "VARIABLE_NAME_NOT_FOUND",
                            f"Node {source_id} does not declare output {variable_name}",
                            node_id=node_id,
                            path=path,
                        )
                    )
                    continue
                source_owner = iteration_owner.get(source_id)
                target_owner = iteration_owner.get(node_id)
                iteration_output = (
                    node.get("type") == "iteration"
                    and path.endswith("output_selector")
                    and source_owner == node_id
                )
                if (
                    source_owner is not None
                    and not iteration_output
                    and target_owner != source_owner
                ):
                    errors.append(
                        ValidationError(
                            "binding",
                            "VARIABLE_SOURCE_OUT_OF_SCOPE",
                            f"Iteration child {source_id} cannot be referenced outside iteration {source_owner}; "
                            f"reference the container output instead",
                            node_id=node_id,
                            path=path,
                        )
                    )
                    continue
                if not iteration_output and source_id not in strict_ancestors(node_id):
                    errors.append(
                        ValidationError(
                            "binding",
                            "VARIABLE_SOURCE_NOT_UPSTREAM",
                            f"Variable source node {source_id} is not an upstream ancestor of node {node_id}",
                            node_id=node_id,
                            path=path,
                        )
                    )
    return errors


def _contract_names(values: Any) -> Set[str]:
    if not isinstance(values, list):
        return set()
    names: Set[str] = set()
    for item in values:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict) and item.get('name'):
            names.add(str(item['name']))
    return names


def validate_requirement_contract(
    workflow: Dict[str, Any],
    spec: Dict[str, Any] | None,
) -> List[ValidationError]:
    if not spec:
        return []
    nodes = workflow.get('nodes_info', [])
    expected_inputs = _contract_names(spec.get('inputs'))
    expected_outputs = _contract_names(spec.get('outputs'))
    actual_inputs: Set[str] = set()
    actual_outputs: Set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        param = node.get('param') or {}
        if node.get('type') == 'start':
            actual_inputs.update(
                str(item[0])
                for item in param.get('variables', [])
                if isinstance(item, list) and item
            )
        elif node.get('type') == 'end':
            actual_outputs.update(
                str(item[0])
                for item in param.get('outputs', [])
                if isinstance(item, list) and item
            )

    errors: List[ValidationError] = []
    if expected_inputs and actual_inputs != expected_inputs:
        errors.append(
            ValidationError(
                'contract',
                'CONTRACT_INPUT_MISMATCH',
                f'Expected inputs {sorted(expected_inputs)}, got {sorted(actual_inputs)}',
            )
        )
    if expected_outputs and actual_outputs != expected_outputs:
        errors.append(
            ValidationError(
                'contract',
                'CONTRACT_OUTPUT_MISMATCH',
                f'Expected outputs {sorted(expected_outputs)}, got {sorted(actual_outputs)}',
            )
        )
    start_ids_by_input: Dict[str, Set[str]] = defaultdict(set)
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "start":
            continue
        start_id = str(node.get("id", ""))
        for variable in (node.get("param") or {}).get("variables", []):
            if isinstance(variable, list) and variable:
                start_ids_by_input[str(variable[0])].add(start_id)

    image_inputs = {
        str(item.get("name"))
        for item in spec.get("inputs", [])
        if isinstance(item, dict)
        and item.get("name")
        and "image" in str(item.get("type", "")).lower()
    }
    for input_name in sorted(image_inputs):
        expected_sources = start_ids_by_input.get(input_name, set())
        vision_bound = any(
            isinstance(node, dict)
            and node.get("type") == "llm"
            and isinstance((node.get("param") or {}).get("vision_variable_selector"), list)
            and len((node.get("param") or {}).get("vision_variable_selector")) == 2
            and str((node.get("param") or {})["vision_variable_selector"][0]) == input_name
            and str((node.get("param") or {})["vision_variable_selector"][1]) in expected_sources
            for node in nodes
        )
        if not vision_bound:
            errors.append(
                ValidationError(
                    "binding",
                    "VISION_BINDING_MISSING",
                    f"Image input {input_name} is never bound to an LLM vision channel",
                )
            )

    return errors

