#!/usr/bin/env python3
"""Build a reproducible report for the frozen five-case developer subset."""
from __future__ import annotations
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

INFRA_MARKERS = (
    "too many clients already",
    "sqlstate 53300",
    "plugindaemoninternalservererror",
    "model doubao-seed-evolving not exist",
)

def read_rows(path: str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["results"]

def key(row: dict) -> tuple[str, str, str]:
    return row["arm"], row["case"], row["input_id"]

def is_infra(row: dict) -> bool:
    text = " ".join(str(row.get(n) or "") for n in ("error", "failure_class", "outputs", "reason")).lower()
    return any(marker in text for marker in INFRA_MARKERS)

def merge_semantic(execution: list[dict], semantic: list[dict]) -> list[dict]:
    judged = {key(row): row for row in semantic}
    merged = []
    for row in execution:
        item = dict(row)
        verdict = judged.get(key(row), {})
        item["semantic_pass"] = bool(verdict.get("semantic_pass"))
        item["semantic_reason"] = verdict.get("reason")
        merged.append(item)
    return merged

def replace_infra_failures(base: list[dict], replacement: list[dict]) -> tuple[list[dict], list[dict]]:
    replacement_by_key = {key(row): row for row in replacement}
    output, audit = [], []
    for row in base:
        candidate = replacement_by_key.get(key(row))
        if is_infra(row) and candidate and candidate.get("execution_pass") and candidate.get("semantic_pass"):
            updated = dict(candidate)
            updated["infra_retry_replaced"] = True
            output.append(updated)
            audit.append({"key": key(row), "original_error": row.get("error") or row.get("failure_class")})
        else:
            output.append(row)
    return output, audit

def ratio(numerator: int, denominator: int) -> str:
    if not denominator:
        return "0/0"
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.1f}%)"

def summarize(rows: list[dict]) -> dict:
    report = {}
    for arm in sorted({row["arm"] for row in rows}):
        arm_rows = [row for row in rows if row["arm"] == arm]
        by_case = defaultdict(list)
        for row in arm_rows:
            by_case[row["case"]].append(row)
        report[arm] = {
            "trials": len(arm_rows),
            "import_publish_pass": sum(
                row.get("setup", {}).get("import_status") == 200
                and row.get("setup", {}).get("publish_status") == 200
                for row in arm_rows
            ),
            "execution_pass": sum(bool(row.get("execution_pass")) for row in arm_rows),
            "output_contract_pass": sum(bool(row.get("output_contract_pass")) for row in arm_rows),
            "semantic_task_pass": sum(bool(row.get("semantic_pass")) for row in arm_rows),
            "stable_task_pass": sum(all(bool(row.get("semantic_pass")) for row in items) for items in by_case.values()),
            "workflow_count": len(by_case),
            "infrastructure_failures": sum(is_infra(row) for row in arm_rows),
            "degraded_artifact_trials": sum(
                any("fallback_markdown_exporter_to_artifact_descriptor" in action for action in row.get("adapter_actions", []))
                for row in arm_rows
            ),
            "directed_repair_trials": sum(bool(row.get("directed_repair_attempts")) for row in arm_rows),
            "directed_repair_attempts": sum(int(row.get("directed_repair_attempts") or 0) for row in arm_rows),
            "failure_classes": dict(Counter(row.get("failure_class") or "none" for row in arm_rows)),
            "per_case": {
                case: {
                    "trials": len(items),
                    "execution_pass": sum(bool(row.get("execution_pass")) for row in items),
                    "output_contract_pass": sum(bool(row.get("output_contract_pass")) for row in items),
                    "semantic_task_pass": sum(bool(row.get("semantic_pass")) for row in items),
                    "stable_task_pass": all(bool(row.get("semantic_pass")) for row in items),
                }
                for case, items in sorted(by_case.items())
            },
        }
    return report

def render(metrics: dict, retry_audit: list[dict]) -> str:
    lines = [
        "# Scoped Developer Evaluation",
        "",
        "> This is a frozen five-workflow developer subset, not a blind test and not a full leaderboard result.",
        "",
        "## Protocol",
        "",
        "- Cases: `Code_1`, `Code_2`, `Code_3`, `Mermaid_1`, `Mermaid_2`.",
        "- Three official functional inputs per workflow: 15 execution trials per arm.",
        "- Same Dify runtime and model; thinking disabled.",
        "- Semantic task success follows the benchmark resolve-stage judge; infrastructure failures are reported separately.",
        "- A workflow is stable only when all three inputs pass semantic evaluation.",
        "- Markdown artifact descriptors are marked degraded and are not claimed as native downloadable files.",
        "",
        "## Results",
        "",
        "| Arm | Import/publish | Execution | Output contract | Semantic task | Stable workflows | Infra failures | Degraded artifacts |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, values in metrics.items():
        lines.append(
            f"| {arm} | {ratio(values['import_publish_pass'], values['trials'])} | "
            f"{ratio(values['execution_pass'], values['trials'])} | "
            f"{ratio(values['output_contract_pass'], values['trials'])} | "
            f"{ratio(values['semantic_task_pass'], values['trials'])} | "
            f"{ratio(values['stable_task_pass'], values['workflow_count'])} | "
            f"{values['infrastructure_failures']} | {values['degraded_artifact_trials']} |"
        )
    lines += ["", "## Per-case semantic results", "", "| Case | " + " | ".join(metrics) + " |", "|---|" + "---:|" * len(metrics)]
    cases = sorted({case for values in metrics.values() for case in values["per_case"]})
    for case in cases:
        cells = []
        for values in metrics.values():
            item = values["per_case"].get(case)
            cells.append(ratio(item["semantic_task_pass"], item["trials"]) if item else "-")
        lines.append(f"| {case} | " + " | ".join(cells) + " |")
    if retry_audit:
        lines += [
            "",
            "## Infrastructure retry audit",
            "",
            f"Exactly {len(retry_audit)} failed trial was replaced after confirming an infrastructure-only failure and rerunning the same input.",
        ]
        for item in retry_audit:
            lines.append(f"- `{item['key'][0]}/{item['key'][1]}/{item['key'][2]}`")
    lines += [
        "",
        "## Interpretation",
        "",
        "The numbers are suitable for regression and engineering validation on this scoped subset. They must not be presented as a full-benchmark or blind-test ranking.",
    ]
    return "\n".join(lines) + "\n"

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--semantic", required=True)
    parser.add_argument("--replacement-result")
    parser.add_argument("--replacement-semantic")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    rows = merge_semantic(read_rows(args.result), read_rows(args.semantic))
    retry_audit: list[dict] = []
    if args.replacement_result and args.replacement_semantic:
        replacement = merge_semantic(read_rows(args.replacement_result), read_rows(args.replacement_semantic))
        rows, retry_audit = replace_infra_failures(rows, replacement)
    metrics = summarize(rows)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps({"metrics": metrics, "infra_retry_audit": retry_audit}, ensure_ascii=False, indent=2), encoding="utf-8")
    compact_rows = []
    for row in rows:
        setup = row.get("setup") or {}
        compact_rows.append({
            "arm": row["arm"],
            "case": row["case"],
            "input_id": row["input_id"],
            "import_status": setup.get("import_status"),
            "publish_status": setup.get("publish_status"),
            "execution_pass": bool(row.get("execution_pass")),
            "output_contract_pass": bool(row.get("output_contract_pass")),
            "semantic_task_pass": bool(row.get("semantic_pass")),
            "failure_class": row.get("failure_class"),
            "infrastructure_failure": is_infra(row),
            "infra_retry_replaced": bool(row.get("infra_retry_replaced")),
            "degraded_artifact": any(
                "fallback_markdown_exporter_to_artifact_descriptor" in action
                for action in row.get("adapter_actions", [])
            ),
            "directed_repair_attempts": int(row.get("directed_repair_attempts") or 0),
        })
    (output / "trials_compact.json").write_text(
        json.dumps(compact_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "SCOPED_DEVELOPER_EVAL.md").write_text(render(metrics, retry_audit), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
