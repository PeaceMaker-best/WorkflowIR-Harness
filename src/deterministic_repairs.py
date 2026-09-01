from __future__ import annotations

import copy
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


def _reference(value: Any) -> Optional[Tuple[str, str]]:
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], (str, int))
    ):
        return str(value[0]), str(value[1])
    return None


def _expected_end_configs(check: Dict[str, Any] | None) -> List[List[str]]:
    if not check:
        return []
    value = check.get("output_var", [])
    if not isinstance(value, list) or not value or not all(isinstance(item, list) for item in value):
        return []
    return [[str(name) for name in item] for item in value]


def _next_numeric_id(ids: Sequence[str]):
    numeric = [int(value) for value in ids if value.isdigit()]
    current = max(numeric, default=0)
    while True:
        current += 1
        yield str(current)


def insert_iteration_array_adapter(
    graph: Dict[str, Any],
    errors: Sequence[Any],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Insert a typed parsing boundary before an iteration node.

    Dify LLM nodes expose text even when prompted for a JSON array, while an
    iteration node requires an actual array. When the validator proves this
    exact mismatch, insert a parameter-extractor so the Binder only has to bind
    the source text and declare an array output.

    The rewrite is deliberately conservative: one target iteration, one direct
    predecessor, and no existing parsing adapter. Otherwise it does nothing.
    """

    targets = {
        str(getattr(error, "node_id", ""))
        for error in errors
        if getattr(error, "code", None) == "INPUT_TYPE_MISMATCH"
        and "requires an array input" in str(getattr(error, "message", ""))
        and getattr(error, "node_id", None) is not None
    }
    if len(targets) != 1:
        return graph, None
    target_id = next(iter(targets))

    candidate = copy.deepcopy(graph)
    nodes = [node for node in candidate.get("nodes", []) if isinstance(node, dict)]
    edges = [
        edge
        for edge in candidate.get("edges", [])
        if isinstance(edge, list) and len(edge) == 3
    ]
    node_by_id = {str(node.get("id")): node for node in nodes}
    if node_by_id.get(target_id, {}).get("type") != "iteration":
        return graph, None

    incoming = [edge for edge in edges if str(edge[2]) == target_id]
    if len(incoming) != 1:
        return graph, None
    source_id = str(incoming[0][0])
    if node_by_id.get(source_id, {}).get("type") in {
        "parameter-extractor",
        "code",
    }:
        return graph, None

    adapter_id = next(_next_numeric_id(list(node_by_id)))
    candidate["nodes"] = nodes + [
        {
            "id": adapter_id,
            "type": "parameter-extractor",
            "role": "Parse upstream text into an array for iteration",
        }
    ]
    candidate["edges"] = [
        edge for edge in edges if edge is not incoming[0]
    ] + [
        [source_id, incoming[0][1], adapter_id],
        [adapter_id, 0, target_id],
    ]
    action = f"insert_iteration_array_adapter:{source_id}->{adapter_id}->{target_id}"
    return candidate, action


def repair_iteration_array_binding(
    workflow: Dict[str, Any],
    errors: Sequence[Any],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Repair a proven string-to-array binding with a typed extractor node."""

    targets = {
        str(getattr(error, "node_id", ""))
        for error in errors
        if getattr(error, "code", None) == "INPUT_TYPE_MISMATCH"
        and "requires an array input" in str(getattr(error, "message", ""))
        and getattr(error, "node_id", None) is not None
    }
    if len(targets) != 1:
        return workflow, None
    target_id = next(iter(targets))

    candidate = copy.deepcopy(workflow)
    nodes = [
        node for node in candidate.get("nodes_info", []) if isinstance(node, dict)
    ]
    edges = [
        edge
        for edge in candidate.get("edges", [])
        if isinstance(edge, list) and len(edge) == 3
    ]
    node_by_id = {str(node.get("id")): node for node in nodes}
    target = node_by_id.get(target_id, {})
    if target.get("type") != "iteration":
        return workflow, None
    selector = (target.get("param") or {}).get("iterator_selector")
    source_ref = _reference(selector)
    if not source_ref:
        return workflow, None
    source_variable, source_id = source_ref
    incoming = [
        edge
        for edge in edges
        if str(edge[0]) == source_id and str(edge[2]) == target_id
    ]
    if len(incoming) != 1:
        return workflow, None
    if node_by_id.get(source_id, {}).get("type") in {
        "parameter-extractor",
        "code",
    }:
        return workflow, None

    adapter_id = next(_next_numeric_id(list(node_by_id)))
    adapter = {
        "id": adapter_id,
        "type": "parameter-extractor",
        "param": {
            "query": [source_variable, source_id],
            "parameters": [
                [
                    "Ordered list of items parsed from the upstream text.",
                    "items",
                    "array[string]",
                ]
            ],
            "instruction": (
                "Extract the complete ordered list from the upstream text. "
                "Return each list item as one string and do not merge items."
            ),
        },
    }
    target.setdefault("param", {})["iterator_selector"] = ["items", adapter_id]
    target_index = next(
        index for index, node in enumerate(nodes) if str(node.get("id")) == target_id
    )
    candidate["nodes_info"] = nodes[:target_index] + [adapter] + nodes[target_index:]
    candidate["edges"] = [
        edge for edge in edges if edge is not incoming[0]
    ] + [
        [source_id, incoming[0][1], adapter_id],
        [adapter_id, 0, target_id],
    ]
    action = f"repair_iteration_array_binding:{source_id}->{adapter_id}->{target_id}"
    return candidate, action


def split_router_end_contract(
    workflow: Dict[str, Any],
    check: Dict[str, Any] | None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Lower a two-branch, merged End node into branch-specific End nodes.

    The Chat2Workflow benchmark represents nested ``output_var`` lists as one
    End contract per branch. Builders often merge both branches through
    variable-aggregator nodes and emit one superset End. This pass traces each
    aggregator input back to the corresponding router branch, clones a
    branch-local aggregator, and emits the exact End contract for that branch.
    It is deliberately conservative and returns the original workflow unless
    the graph shape and every output producer can be proven.
    """

    expected = _expected_end_configs(check)
    if len(expected) != 2:
        return workflow, None

    candidate = copy.deepcopy(workflow)
    nodes = [node for node in candidate.get("nodes_info", []) if isinstance(node, dict)]
    edges = [edge for edge in candidate.get("edges", []) if isinstance(edge, list) and len(edge) == 3]
    node_by_id = {str(node.get("id")): node for node in nodes}
    end_nodes = [node for node in nodes if node.get("type") == "end"]
    if len(end_nodes) != 1:
        return workflow, None

    branch_edges_by_router: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for source, port, target in edges:
        source_id = str(source)
        if node_by_id.get(source_id, {}).get("type") == "if-else" and isinstance(port, int):
            branch_edges_by_router[source_id].append((port, str(target)))
    router_options = [
        (router_id, sorted(values))
        for router_id, values in branch_edges_by_router.items()
        if len({port for port, _ in values}) >= 2
    ]
    if len(router_options) != 1:
        return workflow, None
    _, branch_roots = router_options[0]
    branch_roots = branch_roots[:2]

    old_end = end_nodes[0]
    old_end_id = str(old_end.get("id"))
    old_outputs = {
        str(entry[0]): entry[1]
        for entry in (old_end.get("param") or {}).get("outputs", [])
        if isinstance(entry, list) and len(entry) == 2
    }
    if not all(name in old_outputs for config in expected for name in config):
        return workflow, None

    merge_ids: Set[str] = set()
    for value in old_outputs.values():
        ref = _reference(value)
        if ref and node_by_id.get(ref[1], {}).get("type") == "variable-aggregator":
            merge_ids.add(ref[1])

    adjacency: Dict[str, Set[str]] = defaultdict(set)
    for source, _, target in edges:
        adjacency[str(source)].add(str(target))

    branch_reachable: List[Set[str]] = []
    barriers = merge_ids | {old_end_id}
    for _, root in branch_roots:
        reachable: Set[str] = set()
        queue = deque([root])
        while queue:
            current = queue.popleft()
            if current in reachable or current in barriers:
                continue
            reachable.add(current)
            queue.extend(adjacency.get(current, set()) - reachable)
        branch_reachable.append(reachable)

    selected_by_branch: List[Dict[str, Tuple[str, str, bool]]] = []
    for index, names in enumerate(expected):
        selected: Dict[str, Tuple[str, str, bool]] = {}
        for name in names:
            end_ref = _reference(old_outputs[name])
            if not end_ref:
                return workflow, None
            variable_name, source_id = end_ref
            source_node = node_by_id.get(source_id, {})
            if source_node.get("type") == "variable-aggregator":
                options = [
                    _reference(item)
                    for item in (source_node.get("param") or {}).get("variables", [])
                ]
                match = next(
                    (ref for ref in options if ref and ref[1] in branch_reachable[index]),
                    None,
                )
                if not match:
                    return workflow, None
                selected[name] = (match[0], match[1], True)
            elif source_id in branch_reachable[index]:
                selected[name] = (variable_name, source_id, False)
            else:
                return workflow, None
        selected_by_branch.append(selected)

    removed_ids = merge_ids | {old_end_id}
    new_nodes = [node for node in nodes if str(node.get("id")) not in removed_ids]
    new_edges = [
        edge
        for edge in edges
        if str(edge[0]) not in removed_ids and str(edge[2]) not in removed_ids
    ]
    id_source = _next_numeric_id(list(node_by_id))

    for names, selected in zip(expected, selected_by_branch):
        end_outputs: List[List[Any]] = []
        incoming: Set[str] = set()
        for name in names:
            variable_name, producer_id, was_aggregated = selected[name]
            if was_aggregated:
                aggregator_id = next(id_source)
                new_nodes.append(
                    {
                        "id": aggregator_id,
                        "type": "variable-aggregator",
                        "param": {"variables": [[variable_name, producer_id]]},
                    }
                )
                new_edges.append([producer_id, 0, aggregator_id])
                end_outputs.append([name, ["output", aggregator_id]])
                incoming.add(aggregator_id)
            else:
                end_outputs.append([name, [variable_name, producer_id]])
                incoming.add(producer_id)
        end_id = next(id_source)
        new_nodes.append({"id": end_id, "type": "end", "param": {"outputs": end_outputs}})
        new_edges.extend([[source_id, 0, end_id] for source_id in sorted(incoming)])

    candidate["nodes_info"] = new_nodes
    candidate["edges"] = new_edges
    return candidate, "split_router_end_contract"

def insert_mermaid_sanitizers(
    workflow: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """Insert deterministic fence stripping before Mermaid converter nodes.

    LLMs sometimes return valid Mermaid wrapped in Markdown fences even when the
    prompt forbids it. Dify's Mermaid converter treats the fence as syntax and
    can return an empty file list. This pass only rewrites a direct LLM.text to
    mermaid-converter binding and keeps the rest of the branch unchanged.
    """

    candidate = copy.deepcopy(workflow)
    nodes = [
        node for node in candidate.get("nodes_info", []) if isinstance(node, dict)
    ]
    edges = [
        edge
        for edge in candidate.get("edges", [])
        if isinstance(edge, list) and len(edge) == 3
    ]
    node_by_id = {str(node.get("id")): node for node in nodes}
    id_source = _next_numeric_id(list(node_by_id))
    actions: List[str] = []

    import re

    for converter in list(nodes):
        if converter.get("type") != "mermaid-converter":
            continue
        converter_id = str(converter.get("id"))
        raw = (converter.get("param") or {}).get("mermaid_code")
        source_id: Optional[str] = None
        if isinstance(raw, str):
            match = re.fullmatch(r"\s*\{\{#([^.{}]+)\.text#\}\}\s*", raw)
            if match:
                source_id = match.group(1)
        else:
            ref = _reference(raw)
            if ref and ref[0] == "text":
                source_id = ref[1]
        if not source_id or node_by_id.get(source_id, {}).get("type") != "llm":
            continue

        direct_edges = [
            edge
            for edge in edges
            if str(edge[0]) == source_id and str(edge[2]) == converter_id
        ]
        if len(direct_edges) != 1:
            continue

        sanitizer_id = next(id_source)
        sanitizer = {
            "id": sanitizer_id,
            "type": "code",
            "param": {
                "variables": [["raw", ["text", source_id]]],
                "outputs": [["mermaid_code", "string"]],
                "code": (
                    "import re\n"
                    "\ndef main(raw: str):\n"
                    "\ttext = (raw or '').strip()\n"
                    "\tfence = chr(96) * 3\n"
                    "\tif text.startswith(fence):\n"
                    "\t\tlines = text.splitlines()\n"
                    "\t\ttext = '\\n'.join(lines[1:]) if len(lines) > 1 else ''\n"
                    "\ttext = text.rstrip()\n"
                    "\tif text.endswith(fence):\n"
                    "\t\ttext = text[:-3].rstrip()\n"
                    "\tlines = [line.rstrip() for line in text.splitlines() if line.strip()]\n"
                    "\tif lines and lines[0].strip().lower() == 'mindmap':\n"
                    "\t\tclean = ['mindmap']\n"
                    "\t\tfor line in lines[1:41]:\n"
                    "\t\t\tindent = line[:len(line) - len(line.lstrip())]\n"
                    "\t\t\tlabel = line.strip()\n"
                    "\t\t\tis_root = label.lower().startswith('root')\n"
                    "\t\t\tif is_root:\n"
                    "\t\t\t\tmatch = re.search(r'root\s*\(\((.*?)\)\)', label, re.I)\n"
                    "\t\t\t\tlabel = match.group(1) if match else label[4:]\n"
                    "\t\t\tlabel = re.sub(r'[^\w\u4e00-\u9fff .,-]', ' ', label)\n"
                    "\t\t\tlabel = re.sub(r'\s+', ' ', label).strip()[:64] or 'item'\n"
                    "\t\t\tclean.append(indent + ('root((' + label + '))' if is_root else label))\n"
                    "\t\ttext = '\\n'.join(clean)\n"
                    "\treturn {'mermaid_code': text.strip()}\n"
                ),
            },
        }
        converter.setdefault("param", {})["mermaid_code"] = (
            f"{{{{#{sanitizer_id}.mermaid_code#}}}}"
        )

        for node in nodes:
            if node.get("type") != "variable-aggregator":
                continue
            variables = (node.get("param") or {}).get("variables") or []
            for index, value in enumerate(variables):
                ref = _reference(value)
                if ref == ("text", source_id):
                    variables[index] = ["mermaid_code", sanitizer_id]

        old_edge = direct_edges[0]
        edges = [edge for edge in edges if edge is not old_edge]
        edges.extend(
            [
                [source_id, old_edge[1], sanitizer_id],
                [sanitizer_id, 0, converter_id],
            ]
        )
        insert_at = next(
            index
            for index, node in enumerate(nodes)
            if str(node.get("id")) == converter_id
        )
        nodes.insert(insert_at, sanitizer)
        node_by_id[sanitizer_id] = sanitizer
        actions.append(
            f"insert_mermaid_sanitizer:{source_id}->{sanitizer_id}->{converter_id}"
        )

    candidate["nodes_info"] = nodes
    candidate["edges"] = edges
    return candidate, actions
