#!/usr/bin/env python3
"""Offline regression checks for deterministic harness contract repairs."""
from __future__ import annotations
import argparse
import ast
from pathlib import Path
import yaml
from requirement_contract_repairs import apply_requirement_contract_repairs
from dify_yaml_adapter import patch_runtime_contracts

EXPECTED = {
    "Code_2": {
        "requirement": (
            "repair_cross_language_gate:",
            "add_trace_repair_channel:",
            "bind_case_input_to_translation:",
            "repair_translation_prompt:",
        ),
        "runtime": (
            "repair_python_exec_sandbox:",
            "correct_iteration_output_type:",
            "insert_array_to_text_normalizer:",
        ),
    },
    "Code_3": {
        "requirement": (
            "repair_cross_language_analysis_gate:",
            "repair_cross_language_explanation_prompt:",
        ),
        "runtime": ("fallback_markdown_exporter_to_artifact_descriptor:",),
    },
    "Mermaid_2": {
        "requirement": (),
        "runtime": (
            "correct_variable_aggregator_output_type:",
            "alias_aggregator_output_type:",
        ),
    },
}

def assert_action(actions: list[str], prefix: str, case: str) -> None:
    assert any(action.startswith(prefix) for action in actions), f"{case}: missing {prefix}"

def validate_graph(data: dict, case: str) -> None:
    graph = data["workflow"]["graph"]
    nodes = graph.get("nodes", [])
    ids = [str(node.get("id")) for node in nodes]
    assert len(ids) == len(set(ids)), f"{case}: duplicate node id"
    known = set(ids)
    for edge in graph.get("edges", []):
        assert str(edge.get("source")) in known, f"{case}: dangling source"
        assert str(edge.get("target")) in known, f"{case}: dangling target"
    for node in nodes:
        node_data = node.get("data") or {}
        if node_data.get("type") == "code" and node_data.get("code"):
            ast.parse(str(node_data["code"]))

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yaml-dir", required=True)
    args = parser.parse_args()
    yaml_dir = Path(args.yaml_dir)
    for case, expected in EXPECTED.items():
        data = yaml.safe_load((yaml_dir / f"{case}.yaml").read_text(encoding="utf-8"))
        requirement_actions = apply_requirement_contract_repairs(data)
        runtime_actions = patch_runtime_contracts(data)
        for prefix in expected["requirement"]:
            assert_action(requirement_actions, prefix, case)
        for prefix in expected["runtime"]:
            assert_action(runtime_actions, prefix, case)
        validate_graph(data, case)
        if case == "Code_2":
            text = str(data)
            code_text = "\n".join(str(node.get("data", {}).get("code", "")) for node in data["workflow"]["graph"]["nodes"])
            assert "repair_hint" in text
            assert "case_input" in text
            assert "'iter': iter" in code_text and "'next': next" in code_text
        if case == "Code_3":
            assert "degraded_artifact" in str(data)
    print("PASS: deterministic contract repairs and graph invariants")

if __name__ == "__main__":
    main()
