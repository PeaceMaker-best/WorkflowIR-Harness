from __future__ import annotations

import copy
import re
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from validator import ValidationError, validate_workflow as validate_legacy
from type_contracts import validate_type_contracts


PLACEHOLDER_RE = re.compile(r"\{\{#['\"]?([^.'\"#]+)['\"]?\.([^#]+?)#\}\}")
ADAPTER_ID_RE = re.compile(r"\d+(?:-\d+)?$")


def _declared_outputs(node: Dict[str, Any]) -> Optional[Set[str]]:
    node_type = str(node.get("type"))
    param = node.get("param") or {}
    fixed: Dict[str, Set[str]] = {
        "llm": {"text"},
        "question-classifier": {"class_name"},
        "document-extractor": {"text"},
        "http-request": {"body"},
        "list-operator": {"result", "first_record", "last_record"},
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
        return {
            str(item[0])
            for item in param.get("variables", [])
            if isinstance(item, list) and item
        }
    if node_type == "code":
        return {
            str(item[0])
            for item in param.get("outputs", [])
            if isinstance(item, list) and item
        }
    if node_type == "parameter-extractor":
        return {
            str(item[1])
            for item in param.get("parameters", [])
            if isinstance(item, list) and len(item) >= 2
        }
    return fixed.get(node_type)


def _walk_strings(value: Any, path: str = "") -> Iterable[Tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _walk_strings(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_strings(child, f"{path}[{index}]")


def _replace_placeholders(value: Any, id_map: Dict[str, str]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            source_id, variable = match.group(1), match.group(2)
            return "{{#" + id_map.get(source_id, source_id) + "." + variable + "#}}"

        return PLACEHOLDER_RE.sub(replace, value)
    if isinstance(value, list):
        return [_replace_placeholders(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, id_map) for key, item in value.items()}
    return value


def _reference(value: Any, id_map: Dict[str, str]) -> Any:
    if isinstance(value, list) and len(value) == 2:
        return [value[0], id_map.get(str(value[1]), str(value[1]))]
    return value


def _binding_entries(entries: Any, id_map: Dict[str, str]) -> Any:
    if not isinstance(entries, list):
        return entries
    normalized: List[Any] = []
    for entry in entries:
        if isinstance(entry, list) and len(entry) == 3:
            local_name, source_id, source_variable = entry
            normalized.append(
                [local_name, [source_variable, id_map.get(str(source_id), str(source_id))]]
            )
        elif isinstance(entry, list) and len(entry) == 2:
            local_name, source = entry
            normalized.append([local_name, _reference(source, id_map)])
        else:
            normalized.append(entry)
    return normalized


def _infer_iteration_children(
    nodes: Sequence[Dict[str, Any]], edges: Sequence[Any]
) -> Dict[str, str]:
    node_ids = [str(node.get("id")) for node in nodes]
    node_by_id = {str(node.get("id")): node for node in nodes}
    parents = {
        node_id for node_id, node in node_by_id.items() if node.get("type") == "iteration"
    }
    ownership: Dict[str, str] = {}
    starts: Dict[str, str] = {}
    for node_id, node in node_by_id.items():
        if node.get("type") == "iteration-start":
            owner = next(
                (
                    parent
                    for parent in parents
                    if node_id == f"{parent}-start" or node_id.startswith(f"{parent}-")
                ),
                None,
            )
            if owner:
                ownership[node_id] = owner
                starts[owner] = node_id
        else:
            owner = next(
                (parent for parent in parents if node_id.startswith(f"{parent}-")),
                None,
            )
            if owner:
                ownership[node_id] = owner

    adjacency: Dict[str, Set[str]] = defaultdict(set)
    reverse: Dict[str, Set[str]] = defaultdict(set)
    for edge in edges:
        if isinstance(edge, list) and len(edge) == 3:
            source, target = str(edge[0]), str(edge[2])
            adjacency[source].add(target)
            reverse[target].add(source)

    for parent in parents:
        start = starts.get(parent)
        selector = (node_by_id[parent].get("param") or {}).get("output_selector")
        output_source = str(selector[1]) if isinstance(selector, list) and len(selector) == 2 else None
        if not start or not output_source or output_source not in node_by_id:
            continue

        reachable: Set[str] = set()
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(adjacency.get(current, set()) - reachable)

        ancestors: Set[str] = set()
        queue = deque([output_source])
        while queue:
            current = queue.popleft()
            if current in ancestors:
                continue
            ancestors.add(current)
            queue.extend(reverse.get(current, set()) - ancestors)

        for child_id in reachable & ancestors:
            if child_id != parent:
                ownership[child_id] = parent
    return ownership


def normalize_workflow_for_dify(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Map platform-independent semantic IDs and common binding aliases to Dify's JSON IR."""
    normalized = copy.deepcopy(workflow)
    nodes = normalized.get("nodes_info") or []
    edges = normalized.get("edges") or []
    ownership = _infer_iteration_children(nodes, edges)

    id_map: Dict[str, str] = {}
    outer_nodes = [node for node in nodes if str(node.get("id")) not in ownership]
    for index, node in enumerate(outer_nodes, start=1):
        id_map[str(node.get("id"))] = str(index)

    children: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        node_id = str(node.get("id"))
        if node_id in ownership:
            children[ownership[node_id]].append(node)
    for parent, child_nodes in children.items():
        parent_id = id_map[parent]
        ordered = sorted(
            child_nodes,
            key=lambda node: (node.get("type") != "iteration-start", nodes.index(node)),
        )
        for index, node in enumerate(ordered, start=1):
            id_map[str(node.get("id"))] = f"{parent_id}-{index}"

    for node in nodes:
        old_id = str(node.get("id"))
        node["id"] = id_map.get(old_id, old_id)
        param = _replace_placeholders(node.get("param") or {}, id_map)
        node_type = str(node.get("type"))
        if node_type in {"code", "template-transform"}:
            param["variables"] = _binding_entries(param.get("variables"), id_map)
        if node_type == "end":
            param["outputs"] = _binding_entries(param.get("outputs"), id_map)
        for field in (
            "url",
            "variable",
            "variable_selector",
            "query",
            "iterator_selector",
            "output_selector",
        ):
            if field in param:
                param[field] = _reference(param[field], id_map)
        if node_type == "variable-aggregator" and isinstance(param.get("variables"), list):
            param["variables"] = [_reference(value, id_map) for value in param["variables"]]
        if node_type == "if-else" and isinstance(param.get("cases"), list):
            for case in param["cases"]:
                if not isinstance(case, list) or len(case) != 2 or not isinstance(case[1], list):
                    continue
                for condition in case[1]:
                    if isinstance(condition, list) and condition:
                        condition[0] = _reference(condition[0], id_map)
        node["param"] = param

    for edge in edges:
        if isinstance(edge, list) and len(edge) == 3:
            edge[0] = id_map.get(str(edge[0]), str(edge[0]))
            edge[2] = id_map.get(str(edge[2]), str(edge[2]))
    return normalized


def _contract_errors(workflow: Dict[str, Any]) -> List[ValidationError]:
    errors: List[ValidationError] = []
    nodes = workflow.get("nodes_info") or []
    node_by_id = {
        str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id") is not None
    }
    ids = set(node_by_id)

    for node_id in ids:
        if not ADAPTER_ID_RE.fullmatch(node_id):
            errors.append(
                ValidationError(
                    "adapter",
                    "DIFY_NODE_ID_INVALID",
                    f"Dify adapter requires numeric or iteration child IDs, got {node_id}",
                    node_id=node_id,
                    path="id",
                )
            )

    def check_ref(value: Any, target_id: str, path: str) -> None:
        if not (
            isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], str)
            and isinstance(value[1], (str, int))
        ):
            errors.append(
                ValidationError(
                    "binding",
                    "REFERENCE_SHAPE_INVALID",
                    "Reference must be [source_variable, source_node_id]",
                    node_id=target_id,
                    path=path,
                )
            )
            return
        variable_name, source_id = str(value[0]), str(value[1])
        if source_id not in ids:
            errors.append(
                ValidationError(
                    "binding",
                    "VARIABLE_SOURCE_NOT_FOUND",
                    f"Variable source node {source_id} does not exist",
                    node_id=target_id,
                    path=path,
                )
            )
            return
        declared = _declared_outputs(node_by_id[source_id])
        if declared is not None and variable_name not in declared:
            errors.append(
                ValidationError(
                    "binding",
                    "VARIABLE_NAME_NOT_FOUND",
                    f"Node {source_id} does not declare output {variable_name}",
                    node_id=target_id,
                    path=path,
                )
            )

    for node_id, node in node_by_id.items():
        node_type = str(node.get("type"))
        param = node.get("param") or {}
        if node_type in {"code", "template-transform", "end"}:
            field = "outputs" if node_type == "end" else "variables"
            entries = param.get(field)
            if not isinstance(entries, list):
                errors.append(
                    ValidationError(
                        "binding",
                        "BINDING_LIST_INVALID",
                        f"{field} must be a list",
                        node_id=node_id,
                        path=f"param.{field}",
                    )
                )
            else:
                for index, entry in enumerate(entries):
                    path = f"param.{field}[{index}]"
                    if not isinstance(entry, list) or len(entry) != 2 or not isinstance(entry[0], str):
                        errors.append(
                            ValidationError(
                                "binding",
                                "BINDING_SHAPE_INVALID",
                                "Binding must be [local_name, [source_variable, source_node_id]]",
                                node_id=node_id,
                                path=path,
                            )
                        )
                        continue
                    check_ref(entry[1], node_id, path + "[1]")

        reference_fields = {
            "http-request": ("url",),
            "list-operator": ("variable",),
            "document-extractor": ("variable_selector",),
            "parameter-extractor": ("query",),
            "question-classifier": ("query_variable_selector",),
            "iteration": ("iterator_selector", "output_selector"),
        }.get(node_type, ())
        for field in reference_fields:
            if field in param:
                check_ref(param[field], node_id, f"param.{field}")

        if node_type == "variable-aggregator":
            values = param.get("variables")
            if not isinstance(values, list):
                errors.append(
                    ValidationError(
                        "binding",
                        "BINDING_LIST_INVALID",
                        "variables must be a list",
                        node_id=node_id,
                        path="param.variables",
                    )
                )
            else:
                for index, value in enumerate(values):
                    check_ref(value, node_id, f"param.variables[{index}]")

        if node_type == "if-else":
            cases = param.get("cases")
            if isinstance(cases, list):
                for case_index, case in enumerate(cases):
                    if not isinstance(case, list) or len(case) != 2 or not isinstance(case[1], list):
                        errors.append(
                            ValidationError(
                                "binding",
                                "CASE_SHAPE_INVALID",
                                "Case must be [logical_operator, conditions]",
                                node_id=node_id,
                                path=f"param.cases[{case_index}]",
                            )
                        )
                        continue
                    for condition_index, condition in enumerate(case[1]):
                        if not isinstance(condition, list) or not condition:
                            errors.append(
                                ValidationError(
                                    "binding",
                                    "CONDITION_SHAPE_INVALID",
                                    "Condition must begin with a variable reference",
                                    node_id=node_id,
                                    path=f"param.cases[{case_index}][1][{condition_index}]",
                                )
                            )
                            continue
                        check_ref(
                            condition[0],
                            node_id,
                            f"param.cases[{case_index}][1][{condition_index}][0]",
                        )

        for path, text in _walk_strings(param):
            for source_id, variable_name in PLACEHOLDER_RE.findall(text):
                check_ref([variable_name, source_id], node_id, path)
    return errors


def validate_workflow(
    workflow: Any,
    allowed_types: Set[str],
    schema_by_type: Dict[str, str],
) -> List[ValidationError]:
    """Validate strict base graph invariants before extended binding contracts.

    ``validate_legacy`` is the compatibility entry point and owns the single
    Start, whole-graph reachability, termination, and strict-upstream checks.
    Keeping those checks there means callers of either validator receive the
    same structural guarantees.
    """
    errors = validate_legacy(workflow, allowed_types, schema_by_type)
    if isinstance(workflow, dict):
        errors.extend(_contract_errors(workflow))
        errors.extend(validate_type_contracts(workflow))
    deduplicated: List[ValidationError] = []
    seen: Set[Tuple[Any, ...]] = set()
    for error in errors:
        key = (error.layer, error.code, error.message, error.node_id, error.path)
        if key not in seen:
            seen.add(key)
            deduplicated.append(error)
    return deduplicated
