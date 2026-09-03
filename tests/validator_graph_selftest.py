#!/usr/bin/env python3
"""Regression checks for strict workflow graph and data-flow invariants."""
from __future__ import annotations

import copy

from contract_validator import validate_workflow as validate_contract_workflow
from validator import validate_workflow as validate_base_workflow


ALLOWED_TYPES = {"start", "code", "llm", "iteration", "iteration-start", "end"}
SCHEMAS: dict[str, str] = {}
VALIDATORS = (validate_base_workflow, validate_contract_workflow)


def node(node_id: str, node_type: str, param: dict) -> dict:
    return {"id": node_id, "type": node_type, "param": param}


def codes(validator, workflow: dict) -> set[str]:
    return {
        issue.code
        for issue in validator(workflow, ALLOWED_TYPES, SCHEMAS)
    }


def main() -> None:
    valid = {
        "nodes_info": [
            node("1", "start", {"variables": [["query", "string"]]}),
            node("2", "llm", {"user": "{{#1.query#}}"}),
            node("3", "end", {"outputs": [["answer", ["text", "2"]]]}),
        ],
        "edges": [["1", 0, "2"], ["2", 0, "3"]],
    }

    valid_iteration = {
        "nodes_info": [
            node("1", "start", {"variables": [["items", "array[string]"]]}),
            node(
                "2",
                "iteration",
                {
                    "iterator_selector": ["items", "1"],
                    "output_selector": ["value", "2-2"],
                    "output_type": "array[string]",
                },
            ),
            node("2-1", "iteration-start", {}),
            node(
                "2-2",
                "code",
                {
                    "variables": [["item", ["item", "2"]]],
                    "outputs": [["value", "string"]],
                },
            ),
            node("3", "end", {"outputs": [["result", ["output", "2"]]]}),
        ],
        "edges": [["1", 0, "2"], ["2", 0, "3"], ["2-1", 0, "2-2"]],
    }
    escaped_iteration_child = copy.deepcopy(valid_iteration)
    escaped_iteration_child["nodes_info"][-1]["param"]["outputs"] = [
        ["result", ["value", "2-2"]]
    ]

    multiple_starts = {
        "nodes_info": [
            node("1", "start", {"variables": [["query", "string"]]}),
            node("4", "start", {"variables": [["fallback", "string"]]}),
            node("2", "llm", {"user": "ok"}),
            node("3", "end", {"outputs": [["answer", ["text", "2"]]]}),
        ],
        "edges": [["1", 0, "2"], ["4", 0, "2"], ["2", 0, "3"]],
    }

    disconnected = {
        "nodes_info": valid["nodes_info"] + [
            node("4", "code", {"variables": [], "outputs": [["left", "string"]]}),
            node("5", "code", {"variables": [], "outputs": [["right", "string"]]}),
        ],
        "edges": valid["edges"] + [["4", 0, "5"]],
    }

    dead_end = {
        "nodes_info": valid["nodes_info"] + [
            node("4", "code", {"variables": [], "outputs": [["unused", "string"]]}),
        ],
        "edges": valid["edges"] + [["2", 0, "4"]],
    }

    cross_branch_reference = {
        "nodes_info": [
            node("1", "start", {"variables": [["query", "string"]]}),
            node(
                "2",
                "code",
                {
                    "variables": [["illegal", ["right", "4"]]],
                    "outputs": [["left", "string"]],
                },
            ),
            node("3", "code", {"variables": [], "outputs": [["middle", "string"]]}),
            node("4", "code", {"variables": [], "outputs": [["right", "string"]]}),
            node("5", "end", {"outputs": [["answer", ["left", "2"]]]}),
        ],
        "edges": [
            ["1", 0, "2"],
            ["1", 0, "3"],
            ["3", 0, "4"],
            ["2", 0, "5"],
            ["4", 0, "5"],
        ],
    }

    for validator in VALIDATORS:
        assert not validator(valid, ALLOWED_TYPES, SCHEMAS)
        assert not validator(valid_iteration, ALLOWED_TYPES, SCHEMAS)

        escaped_codes = codes(validator, escaped_iteration_child)
        assert "VARIABLE_SOURCE_OUT_OF_SCOPE" in escaped_codes

        multiple_codes = codes(validator, multiple_starts)
        assert "MULTIPLE_START_NODES" in multiple_codes

        disconnected_codes = codes(validator, disconnected)
        assert "NODE_UNREACHABLE_FROM_START" in disconnected_codes
        assert "NODE_CANNOT_REACH_END" in disconnected_codes

        dead_end_codes = codes(validator, dead_end)
        assert "NODE_CANNOT_REACH_END" in dead_end_codes

        reference_codes = codes(validator, cross_branch_reference)
        assert "VARIABLE_SOURCE_NOT_UPSTREAM" in reference_codes

    print(
        "validator_graph_selftest=PASS "
        "single_start=ENFORCED reachability=ENFORCED strict_upstream=ENFORCED"
    )


if __name__ == "__main__":
    main()
