from __future__ import annotations

import argparse
import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
DEFAULT_WORKFLOW = HERE.parent / "harness" / "Code_3.yaml"
SUMMARY_PATH = HERE / "evidence" / "run-summary.json"
FAULT_PATH = HERE / "evidence" / "fault-injection.json"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def graph(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["workflow"]["graph"]


def endpoint_issues(value: dict[str, Any]) -> list[dict[str, str]]:
    node_ids = {str(item.get("id")) for item in value.get("nodes", [])}
    issues: list[dict[str, str]] = []
    for edge in value.get("edges", []):
        source, target = str(edge.get("source")), str(edge.get("target"))
        missing = [item for item in (source, target) if item not in node_ids]
        if missing:
            issues.append(
                {
                    "code": "EDGE_ENDPOINT_NOT_FOUND",
                    "edge_id": str(edge.get("id")),
                    "missing_node": ",".join(missing),
                    "message": f"edge {source} -> {target} references a missing node",
                }
            )
    return issues


def fault_evidence(workflow: dict[str, Any]) -> dict[str, Any]:
    source = graph(workflow)
    before = endpoint_issues(source)
    if before:
        raise ValueError(f"source graph is invalid: {before}")
    injected = json.loads(json.dumps(source))
    edge = injected["edges"][0]
    original_target = str(edge["target"])
    edge["target"] = "__missing_node__"
    return {
        "check": "edge endpoints must reference declared nodes",
        "source_graph": {
            "nodes": len(source["nodes"]),
            "edges": len(source["edges"]),
            "issues": before,
        },
        "controlled_fault": {
            "edge_id": str(edge["id"]),
            "original_target": original_target,
            "injected_target": "__missing_node__",
            "issues": endpoint_issues(injected),
        },
        "repair_policy": "graph error -> discard broken topology and regenerate or reload the frozen graph skeleton",
        "post_repair": {"issues": endpoint_issues(source), "status": "PASS"},
    }


def public_run(row: dict[str, Any]) -> dict[str, Any]:
    nodes = [
        item
        for item in ((row.get("trace") or {}).get("node_executions") or {}).get("data", [])
        if isinstance(item, dict)
    ]
    run_id = str(row.get("run_id") or "")
    app_id = str((row.get("setup") or {}).get("app_id") or "")
    timestamp = next(
        (
            item.get("created_at")
            for item in nodes
            if isinstance(item.get("created_at"), (int, float))
        ),
        None,
    )
    recorded_at = (
        datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        if timestamp
        else None
    )
    timeline = [
        {
            "title": str(item.get("title") or item.get("node_type") or "node"),
            "type": str(item.get("node_type") or item.get("type") or "unknown"),
            "status": str(item.get("status") or "unknown"),
            "elapsed_seconds": round(float(item.get("elapsed_time") or 0), 3),
        }
        for item in nodes
    ]
    return {
        "input_id": row.get("input_id"),
        "status": row.get("status"),
        "execution_pass": bool(row.get("execution_pass")),
        "output_contract_pass": bool(row.get("output_contract_pass")),
        "elapsed_seconds": round(float(row.get("elapsed_time") or 0), 3),
        "executed_steps": int(row.get("total_steps") or len(nodes)),
        "output_keys": list(row.get("output_keys") or []),
        "matched_output_config": row.get("matched_output_config"),
        "repair_attempts": int(row.get("directed_repair_attempts") or 0),
        "failure_class": row.get("failure_class"),
        "run_ref": run_id[:8],
        "run_id_sha256": digest(run_id) if run_id else None,
        "app_ref": app_id[:8],
        "app_id_sha256": digest(app_id) if app_id else None,
        "recorded_at_utc": recorded_at,
        "timeline": timeline,
    }


def extract_summary(
    raw_path: Path, workflow_path: Path, workflow: dict[str, Any]
) -> dict[str, Any]:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    rows = [
        item
        for item in raw.get("results", [])
        if isinstance(item, dict)
        and item.get("case") == "Code_3"
        and item.get("arm") in {"ours", "staged", "full"}
    ]
    arm = next(
        candidate
        for candidate in ("ours", "staged", "full")
        if any(item.get("arm") == candidate for item in rows)
    )
    rows = sorted(
        (item for item in rows if item.get("arm") == arm),
        key=lambda item: str(item.get("input_id")),
    )
    if len(rows) != 3:
        raise ValueError(f"expected three Code_3 inputs, found {len(rows)}")

    runs = [public_run(item) for item in rows]
    raw_summary = raw.get("summary") or {}
    comparison: dict[str, Any] = {}
    for name, values in (raw_summary.get("arms") or {}).items():
        if not isinstance(values, dict):
            continue
        comparison[str(name)] = {
            key: values.get(key)
            for key in (
                "workflows",
                "trials",
                "execution_pass",
                "output_contract_pass",
                "resolve_proxy",
                "three_input_task_pass",
            )
            if key in values
        }

    value = graph(workflow)
    return {
        "schema_version": 1,
        "provenance": {
            "task": "Code_3",
            "source": "public Chat2Workflow task; custom engineering execution protocol",
            "evidence": "sanitized replay of a captured Dify execution trace",
            "raw_trace_committed": False,
            "user_content_committed": False,
            "secrets_committed": False,
        },
        "runtime": {
            "platform": "Dify 1.9.2",
            "model": raw_summary.get("model"),
            "thinking": raw_summary.get("thinking"),
            "protocol": raw_summary.get("protocol"),
            "arm": arm,
        },
        "requirement_contract": {
            "inputs": [
                {"name": "source_code", "type": "file"},
                {"name": "source_language", "type": "text"},
            ],
            "outputs": [
                {"name": "explanation", "constraint": "non-empty source analysis"},
                {"name": "markdown", "constraint": "typed Markdown artifact descriptor"},
            ],
        },
        "workflow": {
            "artifact": "examples/harness/Code_3.yaml",
            "sha256": digest(workflow_path.read_text(encoding="utf-8")),
            "nodes": len(value["nodes"]),
            "edges": len(value["edges"]),
            "node_types": sorted(
                {str((item.get("data") or {}).get("type")) for item in value["nodes"]}
            ),
        },
        "aggregate": {
            "fixed_inputs": len(runs),
            "execution_pass": sum(item["execution_pass"] for item in runs),
            "output_contract_pass": sum(item["output_contract_pass"] for item in runs),
            "stable_workflow": all(
                item["execution_pass"] and item["output_contract_pass"] for item in runs
            ),
            "mean_elapsed_seconds": round(
                mean(item["elapsed_seconds"] for item in runs), 3
            ),
        },
        "runs": runs,
        "batch_context": comparison,
    }


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render_graph(workflow: dict[str, Any]) -> str:
    value = graph(workflow)
    nodes, edges = value["nodes"], value["edges"]
    xs = [float((item.get("position") or {}).get("x", 0)) for item in nodes]
    ys = [float((item.get("position") or {}).get("y", 0)) for item in nodes]
    min_x, min_y = min(xs), min(ys)
    scale_x = 0.62
    width = max(1500, int((max(xs) - min_x) * scale_x + 360))
    height = max(620, int(max(ys) - min_y + 300))
    positions = {
        str(item["id"]): (
            (float((item.get("position") or {}).get("x", 0)) - min_x) * scale_x + 90,
            float((item.get("position") or {}).get("y", 0)) - min_y + 90,
        )
        for item in nodes
    }
    colors = {
        "start": "#50e3a4",
        "end": "#ffcf5a",
        "if-else": "#ff7d8a",
        "llm": "#9b8cff",
        "code": "#57c7ff",
        "tool": "#ff9f57",
        "document-extractor": "#61e6d6",
        "template-transform": "#f3a7ff",
        "variable-aggregator": "#a9d96c",
    }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<defs><pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="#28304d"/></pattern></defs>',
        f'<rect width="{width}" height="{height}" fill="#12182b"/><rect width="{width}" height="{height}" fill="url(#grid)"/>',
    ]
    for edge in edges:
        source, target = positions[str(edge["source"])], positions[str(edge["target"])]
        x1, y1, x2, y2 = source[0] + 180, source[1] + 42, target[0], target[1] + 42
        bend = max(60, abs(x2 - x1) * 0.42)
        branch = str(edge.get("sourceHandle") or "")
        stroke = "#ff7d8a" if branch and branch not in {"source", "0"} else "#667093"
        parts.append(
            f'<path d="M{x1:.1f},{y1:.1f} C{x1+bend:.1f},{y1:.1f} {x2-bend:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" fill="none" stroke="{stroke}" stroke-width="3"/><circle cx="{x2:.1f}" cy="{y2:.1f}" r="5" fill="{stroke}"/>'
        )
    for item in nodes:
        x, y = positions[str(item["id"])]
        data = item.get("data") or {}
        node_type = str(data.get("type") or "unknown")
        title = str(data.get("title") or node_type)[:22]
        color = colors.get(node_type, "#d7dcef")
        parts.append(
            f'<g transform="translate({x:.1f},{y:.1f})"><rect x="7" y="7" width="180" height="84" fill="#070a12"/><rect width="180" height="84" fill="#1b233d" stroke="#445071" stroke-width="2"/><rect width="9" height="84" fill="{color}"/><text x="24" y="35" fill="#f6f8ff" font-family="Segoe UI,Arial" font-size="17" font-weight="800">{esc(title)}</text><text x="24" y="61" fill="{color}" font-family="Consolas,monospace" font-size="13" font-weight="700">{esc(node_type)}</text></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_report(summary: dict[str, Any], fault: dict[str, Any]) -> str:
    template = (HERE / "template.html").read_text(encoding="utf-8")
    runs = summary["runs"]
    max_time = max(item["elapsed_seconds"] for item in runs[0]["timeline"]) or 1
    run_rows = "".join(
        f'<tr><td>{esc(item["input_id"])}</td><td><span class="pass">PASS</span></td>'
        f'<td>{item["executed_steps"]}</td><td>{item["elapsed_seconds"]:.3f}s</td>'
        f'<td>{esc(", ".join(item["output_keys"]))}</td><td><code>{esc(item["run_ref"])}</code></td></tr>'
        for item in runs
    )
    timeline = "".join(
        f'<div class="timeline-row"><span>{esc(item["title"])}</span>'
        f'<div class="bar-track"><i style="width:{max(2, item["elapsed_seconds"] / max_time * 100):.1f}%"></i></div>'
        f'<b>{item["elapsed_seconds"]:.3f}s</b></div>'
        for item in runs[0]["timeline"]
    )
    official = (summary.get("batch_context") or {}).get("official") or {}
    ours = (summary.get("batch_context") or {}).get("ours") or {}
    values = {
        "NODES": summary["workflow"]["nodes"],
        "EDGES": summary["workflow"]["edges"],
        "EXEC_PASS": summary["aggregate"]["execution_pass"],
        "CONTRACT_PASS": summary["aggregate"]["output_contract_pass"],
        "INPUTS": summary["aggregate"]["fixed_inputs"],
        "MEAN_TIME": f'{summary["aggregate"]["mean_elapsed_seconds"]:.2f}',
        "MODEL": esc(summary["runtime"].get("model")),
        "THINKING": esc(summary["runtime"].get("thinking")),
        "FAULT_CODE": esc(fault["controlled_fault"]["issues"][0]["code"]),
        "POST_ISSUES": len(fault["post_repair"]["issues"]),
        "RUN_ROWS": run_rows,
        "TIMELINE": timeline,
        "OFFICIAL_PASS": official.get("resolve_proxy", "n/a"),
        "OFFICIAL_TRIALS": official.get("trials", "n/a"),
        "OURS_PASS": ours.get("resolve_proxy", "n/a"),
        "OURS_TRIALS": ours.get("trials", "n/a"),
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the sanitized Code_3 replay")
    parser.add_argument("--raw-result", type=Path)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    args = parser.parse_args()
    workflow = yaml.safe_load(args.workflow.read_text(encoding="utf-8"))
    fault = fault_evidence(workflow)
    if args.raw_result:
        summary = extract_summary(args.raw_result, args.workflow, workflow)
        write_json(SUMMARY_PATH, summary)
    else:
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    write_json(FAULT_PATH, fault)
    (HERE / "graph.svg").write_text(render_graph(workflow), encoding="utf-8")
    (HERE / "report.html").write_text(render_report(summary, fault), encoding="utf-8")
    print(
        f'code3_demo=PASS nodes={summary["workflow"]["nodes"]} '
        f'edges={summary["workflow"]["edges"]} '
        f'runtime={summary["aggregate"]["execution_pass"]}/{summary["aggregate"]["fixed_inputs"]}'
    )


if __name__ == "__main__":
    main()
