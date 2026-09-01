from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from validator import ValidationError


def _ref(value: Any) -> Optional[tuple[str, str]]:
    if isinstance(value, list) and len(value) == 2:
        return str(value[0]), str(value[1])
    return None


def _normalize_type(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).lower().replace(" ", "")
    aliases = {
        "paragraph": "string",
        "text": "string",
        "file-list": "array[file]",
        "list[file]": "array[file]",
        "list[string]": "array[string]",
    }
    return aliases.get(text, text)


def _output_type(node: Dict[str, Any], variable: str) -> Optional[str]:
    node_type = str(node.get("type"))
    param = node.get("param") or {}
    if node_type == "start":
        for item in param.get("variables", []):
            if isinstance(item, list) and len(item) >= 2 and str(item[0]) == variable:
                return _normalize_type(item[1])
    if node_type == "code":
        for item in param.get("outputs", []):
            if isinstance(item, list) and len(item) >= 2 and str(item[0]) == variable:
                return _normalize_type(item[1])
    fixed = {
        "llm": "string",
        "template-transform": "string",
        "http-request": "string",
        "question-classifier": "string",
        "document-extractor": "string",
        "mermaid-converter": "array[file]",
        "markdown-exporter": "array[file]",
        "tts": "array[file]",
        "text2image": "array[file]",
        "google-search": "array[object]",
    }
    if node_type in fixed:
        return fixed[node_type]
    if node_type == "iteration":
        if variable == "index":
            return "number"
        if variable == "item":
            iterator = _ref(param.get("iterator_selector"))
            return None if iterator is None else "iteration_item"
        if variable == "output":
            return _normalize_type(param.get("output_type"))
    if node_type == "list-operator":
        if variable == "result":
            source = _ref(param.get("variable"))
            return None if source is None else "array[unknown]"
        return "unknown"
    if node_type == "variable-aggregator":
        return _normalize_type(param.get("output_type"))
    return None


def validate_type_contracts(workflow: Dict[str, Any]) -> List[ValidationError]:
    nodes = [node for node in workflow.get("nodes_info", []) if isinstance(node, dict)]
    node_by_id = {str(node.get("id")): node for node in nodes}
    errors: List[ValidationError] = []

    def source_type(value: Any) -> Optional[str]:
        ref = _ref(value)
        if not ref or ref[1] not in node_by_id:
            return None
        return _output_type(node_by_id[ref[1]], ref[0])

    for node in nodes:
        node_id = str(node.get("id"))
        node_type = str(node.get("type"))
        param = node.get("param") or {}
        if node_type == "list-operator":
            actual = source_type(param.get("variable"))
            if actual is not None and not actual.startswith("array["):
                errors.append(
                    ValidationError(
                        "binding",
                        "INPUT_TYPE_MISMATCH",
                        f"List Operator requires an array input, got {actual}",
                        node_id=node_id,
                        path="param.variable",
                    )
                )
        if node_type == "iteration":
            actual = source_type(param.get("iterator_selector"))
            if actual is not None and not actual.startswith("array["):
                errors.append(
                    ValidationError(
                        "binding",
                        "INPUT_TYPE_MISMATCH",
                        f"Iteration requires an array input, got {actual}",
                        node_id=node_id,
                        path="param.iterator_selector",
                    )
                )
        if node_type == "variable-aggregator":
            inferred: Set[str] = set()
            for value in param.get("variables", []):
                value_type = source_type(value)
                if value_type:
                    inferred.add(value_type)
            if len(inferred) > 1:
                errors.append(
                    ValidationError(
                        "binding",
                        "AGGREGATOR_TYPE_MISMATCH",
                        f"Variable Aggregator inputs must share one type, got {sorted(inferred)}",
                        node_id=node_id,
                        path="param.variables",
                    )
                )
    return errors