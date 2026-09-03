#!/usr/bin/env python3
"""Offline checks for final-DSL validation, provenance, and file semantics."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from dify_dsl_validator import validate_dify_dsl
from run_dify_all3 import build_trial_provenance, store_final_dsl
from semantic_judge_runnable import file_only_semantic_result


def document() -> dict:
    return {
        "workflow": {
            "graph": {
                "nodes": [
                    {
                        "id": "1",
                        "data": {
                            "type": "start",
                            "variables": [
                                {"variable": "query", "type": "paragraph"}
                            ],
                        },
                    },
                    {
                        "id": "2",
                        "data": {
                            "type": "end",
                            "outputs": [
                                {
                                    "variable": "answer",
                                    "value_selector": ["1", "query"],
                                }
                            ],
                        },
                    },
                ],
                "edges": [
                    {
                        "source": "1",
                        "target": "2",
                        "sourceHandle": "source",
                        "targetHandle": "target",
                    }
                ],
            }
        }
    }


def main() -> None:
    good = document()
    assert not validate_dify_dsl(good)

    bad = document()
    bad["workflow"]["graph"]["edges"][0]["target"] = "missing"
    codes = {error.code for error in validate_dify_dsl(bad)}
    assert "EDGE_TARGET_NOT_FOUND" in codes

    file_result = file_only_semantic_result(
        {"files": [{"name": "answer.pdf"}]},
        {"files"},
    )
    assert file_result == {
        "semantic_pass": False,
        "semantic_verified": False,
        "reason": "unverified_file_output",
        "unverified_file_fields": ["files"],
    }
    mixed_result = file_only_semantic_result(
        {"answer": "looks correct", "files": [{"name": "answer.pdf"}]},
        {"files"},
    )
    assert mixed_result == {
        "semantic_pass": False,
        "semantic_verified": False,
        "reason": "unverified_file_output",
        "unverified_file_fields": ["files"],
    }
    assert file_only_semantic_result({"answer": "ok"}, {"files"}) is None

    disconnected = document()
    disconnected["workflow"]["graph"]["nodes"].append(
        {"id": "3", "data": {"type": "code"}}
    )
    disconnected_codes = {
        error.code for error in validate_dify_dsl(disconnected)
    }
    assert "TOP_LEVEL_NODE_UNREACHABLE_FROM_START" in disconnected_codes
    assert "TOP_LEVEL_NODE_CANNOT_REACH_END" in disconnected_codes

    cycle = document()
    cycle["workflow"]["graph"]["nodes"].insert(
        1, {"id": "3", "data": {"type": "code"}}
    )
    cycle["workflow"]["graph"]["edges"] = [
        {
            "source": "1",
            "target": "3",
            "sourceHandle": "source",
            "targetHandle": "target",
        },
        {
            "source": "3",
            "target": "2",
            "sourceHandle": "source",
            "targetHandle": "target",
        },
        {
            "source": "2",
            "target": "3",
            "sourceHandle": "source",
            "targetHandle": "target",
        },
    ]
    assert "TOP_LEVEL_CYCLE_DETECTED" in {
        error.code for error in validate_dify_dsl(cycle)
    }

    cross_branch = document()
    graph = cross_branch["workflow"]["graph"]
    graph["nodes"] = [
        {"id": "1", "data": {"type": "start"}},
        {
            "id": "2",
            "data": {
                "type": "code",
                "variables": [
                    {
                        "variable": "illegal",
                        "value_selector": ["3", "answer"],
                    }
                ],
            },
        },
        {"id": "3", "data": {"type": "code"}},
        {"id": "4", "data": {"type": "end"}},
    ]
    graph["edges"] = [
        {"source": "1", "target": "2", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "1", "target": "3", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "2", "target": "4", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "3", "target": "4", "sourceHandle": "source", "targetHandle": "target"},
    ]
    assert "SELECTOR_SOURCE_NOT_UPSTREAM" in {
        error.code for error in validate_dify_dsl(cross_branch)
    }

    iteration = document()
    graph = iteration["workflow"]["graph"]
    graph["nodes"] = [
        {"id": "1", "data": {"type": "start"}},
        {
            "id": "2",
            "data": {
                "type": "iteration",
                "iterator_selector": ["1", "items"],
                "output_selector": ["2-code", "value"],
            },
        },
        {
            "id": "2-start",
            "parentId": "2",
            "data": {"type": "iteration-start", "isInIteration": True},
        },
        {
            "id": "2-code",
            "parentId": "2",
            "data": {
                "type": "code",
                "isInIteration": True,
                "iteration_id": "2",
                "variables": [
                    {"variable": "item", "value_selector": ["2", "item"]}
                ],
            },
        },
        {
            "id": "3",
            "data": {
                "type": "end",
                "outputs": [
                    {"variable": "answer", "value_selector": ["2", "output"]}
                ],
            },
        },
    ]
    graph["edges"] = [
        {"source": "1", "target": "2", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "2", "target": "3", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "2-start", "target": "2-code", "sourceHandle": "source", "targetHandle": "target"},
    ]
    assert not validate_dify_dsl(iteration)
    escaped_iteration = deepcopy(iteration)
    escaped_iteration["workflow"]["graph"]["nodes"][-1]["data"]["outputs"][0]["value_selector"] = ["2-code", "value"]
    assert "SELECTOR_SOURCE_OUT_OF_SCOPE" in {
        error.code for error in validate_dify_dsl(escaped_iteration)
    }

    disconnected_iteration = deepcopy(iteration)
    disconnected_iteration["workflow"]["graph"]["nodes"].append(
        {
            "id": "2-orphan",
            "parentId": "2",
            "data": {
                "type": "code",
                "isInIteration": True,
                "iteration_id": "2",
            },
        }
    )
    disconnected_iteration_codes = {
        error.code for error in validate_dify_dsl(disconnected_iteration)
    }
    assert "ITERATION_NODE_UNREACHABLE_FROM_START" in disconnected_iteration_codes
    assert "ITERATION_NODE_CANNOT_REACH_OUTPUT" in disconnected_iteration_codes

    cyclic_iteration = deepcopy(iteration)
    cyclic_graph = cyclic_iteration["workflow"]["graph"]
    cyclic_graph["nodes"].append(
        {
            "id": "2-middle",
            "parentId": "2",
            "data": {
                "type": "code",
                "isInIteration": True,
                "iteration_id": "2",
            },
        }
    )
    cyclic_graph["edges"] = [
        edge
        for edge in cyclic_graph["edges"]
        if not (edge["source"] == "2-start" and edge["target"] == "2-code")
    ]
    cyclic_graph["edges"].extend(
        [
            {"source": "2-start", "target": "2-middle", "sourceHandle": "source", "targetHandle": "target"},
            {"source": "2-middle", "target": "2-code", "sourceHandle": "source", "targetHandle": "target"},
            {"source": "2-code", "target": "2-middle", "sourceHandle": "source", "targetHandle": "target"},
        ]
    )
    assert "ITERATION_CYCLE_DETECTED" in {
        error.code for error in validate_dify_dsl(cyclic_iteration)
    }

    cross_scope_edge = deepcopy(iteration)
    cross_scope_edge["workflow"]["graph"]["edges"].append(
        {"source": "2-code", "target": "3", "sourceHandle": "source", "targetHandle": "target"}
    )
    assert "ITERATION_EDGE_CROSSES_SCOPE" in {
        error.code for error in validate_dify_dsl(cross_scope_edge)
    }

    nested_iteration = document()
    nested_graph = nested_iteration["workflow"]["graph"]
    nested_graph["nodes"] = [
        {"id": "1", "data": {"type": "start"}},
        {
            "id": "2",
            "data": {
                "type": "iteration",
                "iterator_selector": ["1", "items"],
                "output_selector": ["2-code", "value"],
            },
        },
        {"id": "2-start", "parentId": "2", "data": {"type": "iteration-start", "isInIteration": True}},
        {
            "id": "4",
            "parentId": "2",
            "data": {
                "type": "iteration",
                "isInIteration": True,
                "iteration_id": "2",
                "iterator_selector": ["2", "item"],
                "output_selector": ["4-code", "value"],
            },
        },
        {"id": "4-start", "parentId": "4", "data": {"type": "iteration-start", "isInIteration": True}},
        {
            "id": "4-code",
            "parentId": "4",
            "data": {
                "type": "code",
                "isInIteration": True,
                "iteration_id": "4",
                "variables": [{"variable": "item", "value_selector": ["4", "item"]}],
            },
        },
        {
            "id": "2-code",
            "parentId": "2",
            "data": {
                "type": "code",
                "isInIteration": True,
                "iteration_id": "2",
                "variables": [{"variable": "nested", "value_selector": ["4", "output"]}],
            },
        },
        {"id": "3", "data": {"type": "end", "outputs": [{"variable": "answer", "value_selector": ["2", "output"]}]}},
    ]
    nested_graph["edges"] = [
        {"source": "1", "target": "2", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "2", "target": "3", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "2-start", "target": "4", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "4", "target": "2-code", "sourceHandle": "source", "targetHandle": "target"},
        {"source": "4-start", "target": "4-code", "sourceHandle": "source", "targetHandle": "target"},
    ]
    assert not validate_dify_dsl(nested_iteration)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "workflow.yaml"
        source.write_text("workflow: {}\n", encoding="utf-8")
        first = build_trial_provenance(
            source,
            "workflow: {}\n",
            {"test1": {"query": "one"}, "output_var": ["answer"]},
            "provider",
            "model",
            "disabled",
        )
        changed = build_trial_provenance(
            source,
            "workflow: {}\n",
            {"test1": {"query": "two"}, "output_var": ["answer"]},
            "provider",
            "model",
            "disabled",
        )
        assert first["experiment_fingerprint"] != changed["experiment_fingerprint"]
        artifact = store_final_dsl(
            root / "artifacts",
            "staged",
            "Case_1__test1",
            first["final_dsl_sha256"],
            "workflow: {}\n",
        )
        assert artifact is not None
        assert Path(artifact).read_text(encoding="utf-8") == "workflow: {}\n"

    print(
        "evaluation_integrity_selftest=PASS "
        "final_dsl=VALIDATED resume=FINGERPRINTED file_semantics=UNVERIFIED"
    )


if __name__ == "__main__":
    main()
