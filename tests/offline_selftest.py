from pathlib import Path

from retrieval import HybridRetriever, parse_node_catalog
from validator import validate_workflow
from benchmark_contract import apply_control_node_closure, validate_requirement_contract
from deterministic_repairs import insert_mermaid_sanitizers


def main() -> None:
    prompt_path = Path(__file__).parent / "fixtures" / "builder_prompt.txt"
    cards = parse_node_catalog(prompt_path.read_text(encoding="utf-8"))
    schemas = {card.node_type: card.full_schema for card in cards}
    allowed = set(schemas)

    good = {
        "nodes_info": [
            {"id": "1", "type": "start", "param": {"variables": [["query", "string"]]}},
            {"id": "2", "type": "llm", "param": {"system": "", "user": "{{#1.query#}}"}},
            {"id": "3", "type": "end", "param": {"outputs": [["answer", ["text", "2"]]]}},
        ],
        "edges": [["1", 0, "2"], ["2", 0, "3"]],
    }
    assert not validate_workflow(good, allowed, schemas)

    missing_edge = {"nodes_info": good["nodes_info"], "edges": [["1", 0, "9"], ["2", 0, "3"]]}
    graph_codes = {error.code for error in validate_workflow(missing_edge, allowed, schemas)}
    assert "EDGE_ENDPOINT_NOT_FOUND" in graph_codes

    bad_binding = {
        "nodes_info": [
            good["nodes_info"][0],
            {"id": "2", "type": "llm", "param": {"system": "", "user": "{{#9.query#}}"}},
            good["nodes_info"][2],
        ],
        "edges": good["edges"],
    }
    binding_codes = {error.code for error in validate_workflow(bad_binding, allowed, schemas)}
    assert "VARIABLE_SOURCE_NOT_FOUND" in binding_codes

    retriever = HybridRetriever(cards)
    types = [
        card.node_type
        for card, _ in retriever.retrieve_nodes(
            "Read a PDF and summarize it",
            ["document-extractor", "llm"],
            top_k=5,
        )
    ]
    assert "document-extractor" in types and "llm" in types

    branch_spec = {
        "inputs": [{"name": "query"}],
        "outputs": [{"name": "answer"}],
        "branch_requirements": [{"branch": "a"}, {"branch": "b"}],
        "required_node_types": ["start", "llm", "end"],
    }
    closed_spec, closure_actions = apply_control_node_closure(branch_spec, allowed)
    assert closure_actions and "if-else" in closed_spec["required_node_types"]
    branch_codes = {error.code for error in validate_requirement_contract(good, closed_spec)}
    assert "ROUTER_REQUIRED" in branch_codes

    routed = {
        "nodes_info": [
            {"id": "1", "type": "start", "param": {"variables": [["query", "string"]]}},
            {"id": "2", "type": "if-else", "param": {"cases": [[None, [[["query", "1"], "not empty"]]], [None, [[["query", "1"], "empty"]]]]}},
            {"id": "3", "type": "llm", "param": {"system": "", "user": "{{#1.query#}}"}},
            {"id": "4", "type": "llm", "param": {"system": "", "user": "fallback"}},
            {"id": "5", "type": "end", "param": {"outputs": [["answer", ["text", "3"]]]}},
        ],
        "edges": [["1", 0, "2"], ["2", 0, "3"], ["2", 1, "4"], ["3", 0, "5"], ["4", 0, "5"]],
    }
    routed_codes = {error.code for error in validate_requirement_contract(routed, closed_spec)}
    assert "ROUTER_REQUIRED" not in routed_codes
    assert "ROUTER_BRANCH_PORT_MISSING" not in routed_codes

    mermaid = {
        "nodes_info": [
            {"id": "1", "type": "start", "param": {"variables": [["query", "string"]]}},
            {"id": "2", "type": "llm", "param": {"system": "", "user": "{{#1.query#}}"}},
            {"id": "3", "type": "mermaid-converter", "param": {"mermaid_code": "{{#2.text#}}"}},
            {"id": "4", "type": "variable-aggregator", "param": {"variables": [["text", "2"]]}},
            {"id": "5", "type": "end", "param": {"outputs": [["mermaid_code", ["output", "4"]]]}},
        ],
        "edges": [["1", 0, "2"], ["2", 0, "3"], ["3", 0, "4"], ["4", 0, "5"]],
    }
    sanitized, sanitizer_actions = insert_mermaid_sanitizers(mermaid)
    assert sanitizer_actions == ["insert_mermaid_sanitizer:2->6->3"]
    assert ["2", 0, "6"] in sanitized["edges"] and ["6", 0, "3"] in sanitized["edges"]
    assert sanitized["nodes_info"][2]["type"] == "code"
    assert sanitized["nodes_info"][3]["param"]["mermaid_code"] == "{{#6.mermaid_code#}}"
    assert sanitized["nodes_info"][4]["param"]["variables"] == [["mermaid_code", "6"]]

    print(f"offline_selftest=PASS node_cards={len(cards)} retrieval_backend={retriever.backend}")


if __name__ == "__main__":
    main()
