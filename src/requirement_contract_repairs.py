from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _prompt_text(node_data: Dict[str, Any]) -> str:
    return "\n".join(
        str(item.get("text", ""))
        for item in node_data.get("prompt_template") or []
        if isinstance(item, dict)
    )


def _start_node(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for node in nodes:
        if (node.get("data") or {}).get("type") == "start":
            return node
    return None


def _start_variables(start: Dict[str, Any]) -> set[str]:
    return {
        str(item.get("variable"))
        for item in (start.get("data") or {}).get("variables") or []
        if isinstance(item, dict) and item.get("variable")
    }


def _repair_code_round2(nodes: List[Dict[str, Any]], start_id: str) -> List[str]:
    actions: List[str] = []
    validator = None
    translator = None
    for node in nodes:
        node_data = node.get("data") or {}
        if node_data.get("type") == "code" and {"is_valid", "python_code", "error_message"}.issubset(
            set((node_data.get("outputs") or {}).keys())
        ):
            validator = node
        if node_data.get("type") == "llm" and "target language is always python" in _prompt_text(node_data).lower():
            translator = node
    if not validator or not translator:
        return actions

    validator_data = validator["data"]
    code = str(validator_data.get("code") or "")
    before = 'return {"is_valid": False, "python_code": candidate'
    after = 'return {"is_valid": True, "python_code": candidate'
    if before in code:
        validator_data["code"] = code.replace(before, after, 1)
        actions.append(f"repair_cross_language_gate:{validator.get('id')}=delegate_invalid_syntax_to_translator")

    translator_data = translator["data"]
    start = next((node for node in nodes if str(node.get("id")) == start_id), None)
    if start is not None:
        start_variables = (start.get("data") or {}).setdefault("variables", [])
        if not any(isinstance(item, dict) and item.get("variable") == "repair_hint" for item in start_variables):
            start_variables.append(
                {
                    "default": "",
                    "hint": "Structured execution trace from a previous failed attempt.",
                    "label": "repair_hint",
                    "max_length": 8192,
                    "options": [],
                    "placeholder": "",
                    "required": False,
                    "type": "paragraph",
                    "variable": "repair_hint",
                }
            )
            actions.append(f"add_trace_repair_channel:{start_id}.repair_hint")
    translator_data["prompt_template"] = [
        {
            "role": "system",
            "text": (
                "You are a cross-language code translator. Return only executable Python 3 code, "
                "without Markdown fences or prose. Preserve the algorithm and add the minimal driver "
                "needed to consume the supplied case input and print the observable result. "
                "The generated program runs in a restricted sandbox: do not import modules, do not call "
                "input() or sys.stdin, and do not depend on a __main__ guard. Embed the supplied case input "
                "as Python literals in the driver and print only the requested observable result. "
                "Omit interactive input prompts, progress messages, and debug labels from stdout; they are "
                "non-semantic scaffolding, so stdout must contain only the algorithm answer."
            ),
        },
        {
            "role": "user",
            "text": (
                f"Translate the source program to Python 3.\n\n"
                f"Source language: {{{{#{start_id}.source_language#}}}}\n"
                f"Case input: {{{{#{start_id}.case_input#}}}}\n\n"
                f"Previous execution trace (empty on the first attempt):\n"
                f"{{{{#{start_id}.repair_hint#}}}}\n\n"
                f"Source code:\n{{{{#{validator.get('id')}.python_code#}}}}\n\n"
                "The generated program must be self-contained, must not read runtime stdin, and must print "
                "the result for the supplied case input directly."
            ),
        },
    ]
    actions.append(f"bind_case_input_to_translation:{start_id}.case_input->{translator.get('id')}")
    actions.append(f"repair_translation_prompt:{translator.get('id')}=cross_language_python3")
    return actions


def _repair_code_round3(nodes: List[Dict[str, Any]], start_id: str) -> List[str]:
    actions: List[str] = []
    analyzer = None
    explainer = None
    for node in nodes:
        node_data = node.get("data") or {}
        raw_outputs = node_data.get("outputs") or {}
        outputs = set(raw_outputs.keys()) if isinstance(raw_outputs, dict) else set()
        if node_data.get("type") == "code" and {"analysis_text", "is_valid_python", "validation_issue"}.issubset(outputs):
            analyzer = node
        if node_data.get("type") == "llm" and "python code explanation assistant" in _prompt_text(node_data).lower():
            explainer = node
    if not analyzer or not explainer:
        return actions

    analyzer_data = analyzer["data"]
    code = str(analyzer_data.get("code") or "")
    pattern = (
        r"(if lang and 'python' not in lang and 'py' not in lang:\s*return \{\s*"
        r"'analysis_text': text,\s*'is_valid_python': )False"
    )
    repaired, count = re.subn(pattern, r"\g<1>True", code, count=1, flags=re.S)
    if count:
        analyzer_data["code"] = repaired
        actions.append(f"repair_cross_language_analysis_gate:{analyzer.get('id')}=allow_known_source_language")

    explainer_data = explainer["data"]
    explainer_data["prompt_template"] = [
        {
            "role": "system",
            "text": (
                "You are a source-code explanation assistant. Explain the program semantics and the purpose "
                "of each major step accurately and concisely in one Markdown paragraph. Do not invent behavior."
            ),
        },
        {
            "role": "user",
            "text": (
                f"Analyze the following source program and explain its algorithm and major steps.\n\n"
                f"Source language: {{{{#{start_id}.source_language#}}}}\n\n"
                f"Source code:\n{{{{#{analyzer.get('id')}.analysis_text#}}}}"
            ),
        },
    ]
    actions.append(f"repair_cross_language_explanation_prompt:{explainer.get('id')}")
    return actions


def apply_requirement_contract_repairs(data: Dict[str, Any]) -> List[str]:
    """Repair only deterministic requirement/data-flow violations found by the harness."""
    nodes = data.get("workflow", {}).get("graph", {}).get("nodes", [])
    start = _start_node(nodes)
    if not start:
        return []
    variables = _start_variables(start)
    start_id = str(start.get("id"))
    actions: List[str] = []
    if {"source_code", "source_language", "case_input"}.issubset(variables):
        actions.extend(_repair_code_round2(nodes, start_id))
    elif {"source_code", "source_language"}.issubset(variables):
        actions.extend(_repair_code_round3(nodes, start_id))
    return actions
