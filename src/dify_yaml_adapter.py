from __future__ import annotations

import ast
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple


def _infer_output_type(node_data: Dict[str, Any], variable: str) -> Optional[str]:
    node_type = str(node_data.get("type", ""))
    if variable == "files" or node_data.get("tool_name") in {
        "mermaid_converter",
        "markdown_exporter",
        "md_exporter",
        "tts",
        "z_image_text_2_image",
    }:
        return "array[file]"
    if node_type in {
        "llm",
        "template-transform",
        "http-request",
        "question-classifier",
        "document-extractor",
    }:
        return "string"
    if node_type == "iteration" and variable == "output":
        return node_data.get("output_type")
    if node_type == "variable-aggregator" and variable == "output":
        return node_data.get("output_type")
    if node_type == "code":
        output = (node_data.get("outputs") or {}).get(variable)
        if isinstance(output, dict) and isinstance(output.get("type"), str):
            return output["type"]
    if node_type == "start":
        for item in node_data.get("variables", []):
            if item.get("variable") == variable:
                value = str(item.get("type", ""))
                return {"paragraph": "string", "file-list": "array[file]"}.get(value, value)
    return None


def _stable_numeric_id(*parts: str) -> str:
    digest = hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()
    return str(8_000_000_000_000 + int(digest[:10], 16) % 1_000_000_000_000)


def _edge(source: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    source_id = str(source["id"])
    target_id = str(target["id"])
    source_type = str((source.get("data") or {}).get("type", ""))
    target_type = str((target.get("data") or {}).get("type", ""))
    return {
        "data": {"isInIteration": False, "sourceType": source_type, "targetType": target_type},
        "id": f"{source_id}-source-{target_id}-target",
        "source": source_id,
        "sourceHandle": "source",
        "target": target_id,
        "targetHandle": "target",
        "type": "custom",
        "zIndex": 0,
    }


def _insert_array_to_text_normalizer(
    graph: Dict[str, Any],
    source: Dict[str, Any],
    source_variable: str,
    target: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
    source_id = str(source["id"])
    target_id = str(target["id"])
    normalizer_id = _stable_numeric_id("array-to-text", source_id, source_variable, target_id)
    source_position = source.get("position") or {"x": 0, "y": 0}
    target_position = target.get("position") or {"x": 600, "y": 0}
    position = {
        "x": (float(source_position.get("x", 0)) + float(target_position.get("x", 600))) / 2,
        "y": (float(source_position.get("y", 0)) + float(target_position.get("y", 0))) / 2,
    }
    normalizer = {
        "data": {
            "code": (
                "def main(items: list) -> dict:\n"
                "    if items is None:\n"
                "        return {'text': ''}\n"
                "    if not isinstance(items, list):\n"
                "        return {'text': str(items)}\n"
                "    return {'text': '\\n'.join(str(item) for item in items if item is not None)}\n"
            ),
            "code_language": "python3",
            "desc": "Deterministic contract repair: normalize array output to text.",
            "outputs": {"text": {"children": None, "type": "string"}},
            "selected": False,
            "title": "Contract: Array to Text",
            "type": "code",
            "variables": [{
                "value_selector": [source_id, source_variable],
                "value_type": "array[string]",
                "variable": "items",
            }],
        },
        "height": 54,
        "id": normalizer_id,
        "position": position,
        "positionAbsolute": dict(position),
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "type": "custom",
        "width": 244,
    }
    edges = graph.setdefault("edges", [])
    for edge in edges:
        if str(edge.get("source")) == source_id and str(edge.get("target")) == target_id:
            edge["target"] = normalizer_id
            edge["id"] = f"{source_id}-source-{normalizer_id}-target"
            edge.setdefault("data", {})["targetType"] = "code"
    edges.append(_edge(normalizer, target))
    graph.setdefault("nodes", []).append(normalizer)
    return normalizer, normalizer_id


def _markdown_input_selector(node_data: Dict[str, Any]) -> Optional[List[str]]:
    value = (((node_data.get("tool_parameters") or {}).get("md_text") or {}).get("value"))
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\{\{#([^.{}]+)\.([^#{}]+)#\}\}", value.strip())
    if not match:
        return None
    return [match.group(1), match.group(2)]


def _replace_markdown_exporter(node: Dict[str, Any]) -> bool:
    node_data = node.get("data") or {}
    provider = f"{node_data.get('provider_id', '')} {node_data.get('provider_name', '')}".lower()
    if node_data.get("type") != "tool" or not (
        node_data.get("tool_name") == "md_to_md" or "md_exporter" in provider
    ):
        return False
    selector = _markdown_input_selector(node_data)
    if not selector:
        return False
    node["data"] = {
        "code": (
            "def main(markdown_text: str) -> dict:\n"
            "    text = markdown_text or ''\n"
            "    artifact = {\n"
            "        'filename': 'explanation.md',\n"
            "        'extension': '.md',\n"
            "        'mime_type': 'text/markdown',\n"
            "        'content': text,\n"
            "        'degraded_artifact': True,\n"
            "    }\n"
            "    return {'files': [artifact]}\n"
        ),
        "code_language": "python3",
        "desc": "Bounded fallback when the optional Markdown exporter plugin is unavailable.",
        "outputs": {"files": {"children": None, "type": "array[object]"}},
        "selected": False,
        "title": "Fallback: Markdown Artifact",
        "type": "code",
        "variables": [{
            "value_selector": selector,
            "value_type": "string",
            "variable": "markdown_text",
        }],
    }
    return True


def _repair_obvious_python_indentation(node_data: Dict[str, Any]) -> Optional[str]:
    if node_data.get("type") != "code" or node_data.get("code_language") not in {None, "python3"}:
        return None
    code = str(node_data.get("code") or "")
    try:
        ast.parse(code)
        return None
    except IndentationError as exc:
        line_number = int(exc.lineno or 0)
    except SyntaxError:
        return None
    lines = code.splitlines()
    if line_number < 2 or line_number > len(lines):
        return None
    previous = lines[line_number - 2]
    current = lines[line_number - 1]
    if not previous.rstrip().endswith(":"):
        return None
    previous_indent = previous[: len(previous) - len(previous.lstrip())]
    current_indent = current[: len(current) - len(current.lstrip())]
    if len(current_indent.expandtabs(4)) > len(previous_indent.expandtabs(4)):
        return None
    unit = "\t" if "\t" in previous_indent else "    "
    lines[line_number - 1] = previous_indent + unit + current.lstrip()
    repaired = "\n".join(lines)
    try:
        ast.parse(repaired)
    except SyntaxError:
        return None
    node_data["code"] = repaired
    return f"line_{line_number}"


def patch_runtime_contracts(
    data: Dict[str, Any],
    model_provider: Optional[str] = None,
    model_name: Optional[str] = None,
    thinking_mode: str = "disabled",
    allow_artifact_fallback: bool = True,
) -> List[str]:
    """Fill runtime contracts and bind every model-backed node to one test model."""
    if thinking_mode not in {"disabled", "enabled"}:
        raise ValueError(f"unsupported thinking mode: {thinking_mode}")
    graph = data.get("workflow", {}).get("graph", {})
    nodes = graph.get("nodes", [])
    node_by_id = {str(node.get("id")): node for node in nodes}
    actions: List[str] = []
    for node in list(nodes):
        node_data = node.get("data") or {}
        repaired_line = _repair_obvious_python_indentation(node_data)
        if repaired_line:
            actions.append(f"repair_code_node_indentation:{node.get('id')}={repaired_line}")
        code = str(node_data.get("code") or "")
        if "SAFE_BUILTINS = {" in code and "'__import__': _safe_import" not in code:
            safe_import = (
                "_SAFE_IMPORT_ROOTS = {'math', 'statistics', 'collections', 'heapq', 'itertools', "
                "'functools', 'bisect', 'io', 're', 'json'}\n"
                "def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):\n"
                "    root = str(name).split('.', 1)[0]\n"
                "    if root not in _SAFE_IMPORT_ROOTS:\n"
                "        raise ImportError(f'module {name!r} is not allowed in this sandbox')\n"
                "    return __import__(name, globals, locals, fromlist, level)\n\n"
            )
            safe_entries = (
                "SAFE_BUILTINS = {\n"
                "        '__import__': _safe_import,\n        '__build_class__': __build_class__,\n"
                "        'object': object,\n        'staticmethod': staticmethod,\n        'classmethod': classmethod,\n"
                "        'property': property,\n        'isinstance': isinstance,\n        'issubclass': issubclass,\n"
                "        'getattr': getattr,\n        'setattr': setattr,\n        'hasattr': hasattr,\n"
                "        'Exception': Exception,\n        'ValueError': ValueError,\n        'TypeError': TypeError,\n"
                "        'iter': iter,\n        'next': next,"
            )
            code = code.replace("SAFE_BUILTINS = {", safe_import + safe_entries, 1)
            node_data["code"] = code
            actions.append(f"repair_python_exec_sandbox:{node.get('id')}=allow_safe_stdlib_imports")
        sandbox_before = "sandbox_globals = {'__builtins__': SAFE_BUILTINS}"
        sandbox_after = "sandbox_globals = {'__builtins__': SAFE_BUILTINS, '__name__': '__main__'}"
        if sandbox_before in code:
            code = code.replace(sandbox_before, sandbox_after, 1)
            actions.append(f"repair_python_exec_sandbox:{node.get('id')}=set_dunder_name")
        if "sandbox_globals, {})" in code:
            code = code.replace("sandbox_globals, {})", "sandbox_globals, sandbox_globals)", 1)
            actions.append(f"repair_python_exec_sandbox:{node.get('id')}=shared_exec_namespace")
        if code != str(node_data.get("code") or ""):
            node_data["code"] = code

    model_node_types = {"llm", "question-classifier", "parameter-extractor"}
    for node in nodes:
        node_data = node.get("data") or {}
        node_type = str(node_data.get("type", ""))
        if node_type not in model_node_types or not (model_provider and model_name):
            continue
        model = node_data.setdefault("model", {})
        model["provider"] = model_provider
        model["name"] = model_name
        model.setdefault("mode", "chat")
        completion = model.setdefault("completion_params", {})
        completion["enable_thinking"] = thinking_mode == "enabled"
        completion["temperature"] = 0.0
        current_max_tokens = completion.get("max_tokens", 4096)
        if not isinstance(current_max_tokens, int) or current_max_tokens > 4096:
            completion["max_tokens"] = 4096
        actions.append(
            f"rewrite_model:{node_type}:{node.get('id')}="
            f"{model_provider}/{model_name};thinking={thinking_mode}"
        )
    if allow_artifact_fallback:
        for node in list(nodes):
            if not _replace_markdown_exporter(node):
                continue
            node_id = str(node.get("id"))
            for edge in graph.get("edges", []):
                if str(edge.get("source")) == node_id:
                    edge.setdefault("data", {})["sourceType"] = "code"
                if str(edge.get("target")) == node_id:
                    edge.setdefault("data", {})["targetType"] = "code"
            actions.append(f"fallback_markdown_exporter_to_artifact_descriptor:{node_id}")

    for node in nodes:
        node_data = node.get("data") or {}
        if node_data.get("type") != "http-request":
            continue
        timeout = node_data.setdefault("timeout", {})
        changed = False
        for key, value in {
            "max_connect_timeout": 10,
            "max_read_timeout": 30,
            "max_write_timeout": 30,
        }.items():
            if not isinstance(timeout.get(key), (int, float)) or timeout.get(key, 0) <= 0:
                timeout[key] = value
                changed = True
        if changed:
            actions.append(f"bound_http_timeouts:{node.get('id')}=10/30/30")
    for node in list(nodes):
        node_data = node.get("data") or {}
        if node_data.get("type") != "iteration":
            continue
        selector = node_data.get("output_selector")
        if not isinstance(selector, list) or len(selector) < 2:
            continue
        source_id, variable = str(selector[0]), str(selector[1])
        source_data = (node_by_id.get(source_id) or {}).get("data") or {}
        item_type = _infer_output_type(source_data, variable)
        if not item_type:
            continue
        expected = f"array[{item_type}]"
        before = node_data.get("output_type")
        if before != expected:
            node_data["output_type"] = expected
            actions.append(f"correct_iteration_output_type:{node.get('id')}={before}->{expected}")

    for node in list(nodes):
        node_data = node.get("data") or {}
        if node_data.get("type") != "variable-aggregator":
            continue
        variables = node_data.get("variables") or []
        typed_inputs = []
        for reference in variables:
            if not isinstance(reference, list) or len(reference) < 2:
                continue
            source_id, variable = str(reference[0]), str(reference[1])
            source_node = node_by_id.get(source_id) or {}
            inferred = _infer_output_type(source_node.get("data") or {}, variable)
            if inferred:
                typed_inputs.append((reference, source_node, variable, inferred))
        unique_types = {item[3] for item in typed_inputs}
        expected = None
        if len(unique_types) == 1:
            expected = next(iter(unique_types))
        elif unique_types == {"string", "array[string]"}:
            for reference, source_node, variable, inferred in typed_inputs:
                if inferred != "array[string]":
                    continue
                normalizer, normalizer_id = _insert_array_to_text_normalizer(
                    graph, source_node, variable, node
                )
                reference[:] = [normalizer_id, "text"]
                node_by_id[normalizer_id] = normalizer
                actions.append(
                    f"insert_array_to_text_normalizer:{source_node.get('id')}->{normalizer_id}->{node.get('id')}"
                )
            expected = "string"
        elif unique_types:
            actions.append(
                f"unresolved_aggregator_type_union:{node.get('id')}={','.join(sorted(unique_types))}"
            )
        if expected and node_data.get("output_type") != expected:
            before = node_data.get("output_type")
            node_data["output_type"] = expected
            actions.append(f"correct_variable_aggregator_output_type:{node.get('id')}={before}->{expected}")
    for node in nodes:
        node_data = node.get("data") or {}
        if node_data.get("type") == "iteration" and not node_data.get("is_parallel"):
            node_data["is_parallel"] = True
            node_data["parallel_nums"] = 10
            actions.append(f"enable_parallel_iteration:{node.get('id')}=10")

    iteration_inputs: Dict[str, List[str]] = {}
    for node in nodes:
        node_data = node.get("data") or {}
        if node_data.get("type") != "iteration":
            continue
        selector = node_data.get("iterator_selector")
        if isinstance(selector, list) and len(selector) == 2:
            iteration_inputs.setdefault(str(selector[0]), []).append(str(selector[1]))
    for node in nodes:
        node_id = str(node.get("id"))
        node_data = node.get("data") or {}
        if node_data.get("type") != "code" or node_id not in iteration_inputs:
            continue
        code = str(node_data.get("code") or "")
        for variable in iteration_inputs[node_id]:
            changed = False
            for quote in ("'", '"'):
                before = f"{quote}{variable}{quote}: {variable}"
                after = f"{quote}{variable}{quote}: {variable}[:29]"
                if before in code and after not in code:
                    code = code.replace(before, after, 1)
                    changed = True
                    break
            if changed:
                actions.append(f"cap_iteration_input:{node_id}:{variable}=29")
        node_data["code"] = code

    type_aliases = {"file": "object", "array[file]": "array[object]"}
    for node in nodes:
        node_data = node.get("data") or {}
        node_type = str(node_data.get("type", ""))
        if node_type == "code":
            for name, output in (node_data.get("outputs") or {}).items():
                if isinstance(output, dict) and output.get("type") in type_aliases:
                    before = str(output["type"])
                    output["type"] = type_aliases[before]
                    actions.append(f"alias_code_output_type:{node.get('id')}:{name}={before}->{output['type']}")
        elif node_type == "variable-aggregator":
            before = node_data.get("output_type")
            if before in type_aliases:
                node_data["output_type"] = type_aliases[before]
                actions.append(f"alias_aggregator_output_type:{node.get('id')}={before}->{node_data['output_type']}")
        elif node_type == "end":
            for output in node_data.get("outputs") or []:
                before = output.get("value_type") if isinstance(output, dict) else None
                if before in type_aliases:
                    output["value_type"] = type_aliases[before]
                    actions.append(f"alias_end_output_type:{node.get('id')}:{output.get('variable')}={before}->{output['value_type']}")
    return actions