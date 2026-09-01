from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Set, Tuple

from validator import ValidationError


ROUTER_NODE_TYPES = {"if-else", "question-classifier"}


def _branch_specs(spec: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if not isinstance(spec, dict):
        return []
    value = spec.get("branch_requirements")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _distinct_branch_input_drivers(spec: Dict[str, Any]) -> Set[str]:
    input_names = _named_contract_items(spec.get("inputs"))
    drivers: Set[str] = set()
    for branch in _branch_specs(spec):
        condition = str(branch.get("condition", "")).lower()
        matches = {name for name in input_names if name.lower() in condition}
        if len(matches) == 1:
            drivers.update(matches)
    return drivers


def apply_control_node_closure(
    spec: Dict[str, Any],
    available_node_types: Iterable[str] | None = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Force an appropriate router into progressive schema disclosure."""
    closed = copy.deepcopy(spec)
    actions: List[str] = []
    branches = _branch_specs(closed)
    if len(branches) < 2:
        return closed, actions

    available = set(available_node_types or ROUTER_NODE_TYPES)
    required = [str(value) for value in closed.get("required_node_types", []) if value]
    optional = [str(value) for value in closed.get("optional_node_types", []) if value]
    distinct_drivers = _distinct_branch_input_drivers(closed)

    if len(distinct_drivers) >= 2 and "if-else" in available:
        required = [value for value in required if value != "question-classifier"]
        optional = [value for value in optional if value != "question-classifier"]
        if "if-else" not in required:
            required.append("if-else")
        closed["required_node_types"] = list(dict.fromkeys(required))
        closed["optional_node_types"] = list(dict.fromkeys(optional))
        actions.append(
            "deterministic_router_closure:if-else:inputs="
            + ",".join(sorted(distinct_drivers))
        )
        return closed, actions

    if ROUTER_NODE_TYPES.intersection(required + optional):
        return closed, actions
    router = "if-else" if "if-else" in available else "question-classifier"
    if router not in available:
        return closed, actions
    required.append(router)
    closed["required_node_types"] = list(dict.fromkeys(required))
    actions.append(f"control_node_closure:{router}:branches={len(branches)}")
    return closed, actions


def _start_variables(workflow: Dict[str, Any]) -> Set[str]:
    values: Set[str] = set()
    for node in workflow.get("nodes_info", []):
        if isinstance(node, dict) and node.get("type") == "start":
            for item in (node.get("param") or {}).get("variables", []):
                if isinstance(item, list) and item:
                    values.add(str(item[0]))
    return values


def _end_variable_configs(workflow: Dict[str, Any]) -> List[Set[str]]:
    configs: List[Set[str]] = []
    for node in workflow.get("nodes_info", []):
        if isinstance(node, dict) and node.get("type") == "end":
            values: Set[str] = set()
            for item in (node.get("param") or {}).get("outputs", []):
                if isinstance(item, list) and item:
                    values.add(str(item[0]))
            configs.append(values)
    return configs


def _output_configs(value: Any) -> List[Set[str]]:
    if not isinstance(value, list):
        return [set()]
    if value and all(isinstance(item, list) for item in value):
        return [{str(name) for name in item} for item in value]
    return [{str(name) for name in value}]


def _canonical_configs(configs: List[Set[str]]) -> List[tuple[str, ...]]:
    return sorted(tuple(sorted(config)) for config in configs)


def _named_contract_items(value: Any) -> Set[str]:
    if not isinstance(value, list):
        return set()
    names: Set[str] = set()
    for item in value:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
        elif isinstance(item, str):
            names.add(item)
    return names


def validate_requirement_contract(
    workflow: Any,
    spec: Dict[str, Any] | None,
) -> List[ValidationError]:
    """Validate only contracts derived from the model's confirmed Requirement Spec.

    Unlike validate_benchmark_contract, this function never reads benchmark labels
    and is safe to feed back into the repair loop.
    """
    if not isinstance(workflow, dict) or not isinstance(spec, dict):
        return []
    errors: List[ValidationError] = []
    expected_inputs = _named_contract_items(spec.get("inputs"))
    expected_outputs = _named_contract_items(spec.get("outputs"))
    actual_inputs = _start_variables(workflow)
    actual_output_sets = _end_variable_configs(workflow)
    actual_outputs = set().union(*actual_output_sets) if actual_output_sets else set()

    if expected_inputs and actual_inputs != expected_inputs:
        errors.append(
            ValidationError(
                "consistency",
                "REQUIREMENT_INPUT_MISMATCH",
                f"Requirement inputs {sorted(expected_inputs)}; got {sorted(actual_inputs)}",
            )
        )
    if expected_outputs and actual_outputs != expected_outputs:
        errors.append(
            ValidationError(
                "consistency",
                "REQUIREMENT_OUTPUT_MISMATCH",
                f"Requirement outputs {sorted(expected_outputs)}; got {sorted(actual_outputs)}",
            )
        )

    actual_types = {
        str(node.get("type"))
        for node in workflow.get("nodes_info", [])
        if isinstance(node, dict)
    }
    required_types = {
        str(value) for value in spec.get("required_node_types", []) if value
    }
    for node_type in sorted(required_types - actual_types):
        errors.append(
            ValidationError(
                "consistency",
                "REQUIREMENT_CAPABILITY_MISSING",
                f"Requirement-derived capability {node_type} is missing",
            )
        )
    forbidden_types = {
        str(value) for value in spec.get("forbidden_node_types", []) if value
    }
    for node_type in sorted(forbidden_types & actual_types):
        errors.append(
            ValidationError(
                "consistency",
                "REQUIREMENT_FORBIDDEN_CAPABILITY",
                f"Requirement forbids capability {node_type}",
            )
        )

    branches = _branch_specs(spec)
    if len(branches) >= 2:
        deterministic_router = len(_distinct_branch_input_drivers(spec)) >= 2
        if deterministic_router and "if-else" not in actual_types:
            errors.append(
                ValidationError(
                    "graph",
                    "DETERMINISTIC_ROUTER_REQUIRED",
                    "Branches driven by distinct optional inputs must use if-else, not semantic classification",
                )
            )
        router_ids = {
            str(node.get("id"))
            for node in workflow.get("nodes_info", [])
            if isinstance(node, dict) and str(node.get("type")) in ROUTER_NODE_TYPES
        }
        if not router_ids:
            errors.append(
                ValidationError(
                    "graph",
                    "ROUTER_REQUIRED",
                    f"Requirement declares {len(branches)} branches but the graph has no control-flow router",
                )
            )
        else:
            ports = {
                int(edge[1])
                for edge in workflow.get("edges", [])
                if isinstance(edge, list)
                and len(edge) == 3
                and str(edge[0]) in router_ids
                and isinstance(edge[1], int)
            }
            if len(ports) < 2:
                errors.append(
                    ValidationError(
                        "graph",
                        "ROUTER_BRANCH_PORT_MISSING",
                        "A multi-branch requirement must leave a router through at least two distinct ports",
                    )
                )
    return errors

def validate_benchmark_contract(
    workflow: Any,
    check: Dict[str, Any] | None,
) -> List[ValidationError]:
    if not isinstance(workflow, dict) or not check:
        return []
    errors: List[ValidationError] = []
    actual_inputs = _start_variables(workflow)
    actual_outputs = _end_variable_configs(workflow)
    expected_inputs = {str(name) for name in check.get("input_var", [])}
    expected_outputs = _output_configs(check.get("output_var", []))

    if actual_inputs != expected_inputs:
        errors.append(
            ValidationError(
                "consistency",
                "INPUT_CONTRACT_MISMATCH",
                f"Expected workflow inputs {sorted(expected_inputs)}; got {sorted(actual_inputs)}",
            )
        )
    if _canonical_configs(actual_outputs) != _canonical_configs(expected_outputs):
        errors.append(
            ValidationError(
                "consistency",
                "OUTPUT_CONTRACT_MISMATCH",
                f"Expected End-node outputs {_canonical_configs(expected_outputs)}; got {_canonical_configs(actual_outputs)}",
            )
        )

    actual_types = {
        str(node.get("type"))
        for node in workflow.get("nodes_info", [])
        if isinstance(node, dict)
    }
    for node_type in check.get("related_nodes", []):
        if str(node_type) not in actual_types:
            errors.append(
                ValidationError(
                    "consistency",
                    "REQUIRED_NODE_MISSING",
                    f"Required node type {node_type} is missing",
                )
            )
    return errors
