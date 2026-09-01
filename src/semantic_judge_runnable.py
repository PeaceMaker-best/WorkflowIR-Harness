from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from api_client import APIClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--max-output-chars", type=int, default=16000)
    parser.add_argument("--benchmark-repo", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo = Path(args.benchmark_repo).resolve()
    checks = json.loads((repo / "dataset/check_pass_stage.json").read_text())
    file_checks = json.loads((repo / "dataset/check_resolve_stage.json").read_text())
    task_rows = json.loads((repo / "dataset/query.json").read_text())
    tasks = {row["task"]: row for row in task_rows}
    system = (repo / "prompts/evaluation_resolve_system.txt").read_text().strip()
    rows = json.loads(Path(args.input).read_text())["results"]
    client = APIClient(
        args.base_url,
        args.model,
        args.key_file,
        temperature=0.0,
        max_tokens=800,
        transport_retries=2,
        thinking_mode="disabled",
        request_timeout=300,
    )

    def judge(item: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "arm": item["arm"],
            "case": item["case"],
            "input_id": item["input_id"],
            "execution_pass": bool(item.get("resolve_proxy")),
        }
        if not item.get("resolve_proxy"):
            result.update({"semantic_pass": False, "reason": "execution_or_output_contract_failed"})
            return result
        case = item["case"]
        task_name, round_text = case.rsplit("_", 1)
        round_id = int(round_text)
        test = checks[case][item["input_id"]]
        output_dict = ((item.get("trace") or {}).get("detail") or {}).get("outputs") or {}
        file_names = set((file_checks.get(case) or {}).keys())
        nonfile_outputs = [[key, value] for key, value in output_dict.items() if key not in file_names]
        if not nonfile_outputs:
            result.update({"semantic_pass": True, "reason": "file_outputs_checked_separately"})
            return result
        output_text = "\n".join(f"{key}: {value}" for key, value in nonfile_outputs)
        if len(output_text) > args.max_output_chars:
            output_text = output_text[: args.max_output_chars] + "\n[truncated by low-cost judge]"
        input_text = "\n".join(
            f"{key}: {value}"
            for key, value in test.items()
            if key != "ground_truth" and value != "" and not isinstance(value, (dict, list))
        )
        task = tasks[task_name]
        queries = "\n".join(
            f"query{index}: {task[f'query{index}']}"
            for index in range(1, round_id + 1)
        )
        user = (
            f"<queries>\n{queries}\n</queries>\n\n"
            f"<input>\n{input_text}\n</input>\n\n"
            f"<output>\n{output_text}\n</output>\n\n"
            f"<reference_answer>\n{test.get('ground_truth', '')}\n</reference_answer>"
        )
        try:
            response = client.complete(system, user)
            match = re.search(r"<result>\s*(true|false)\s*</result>", response.text, re.I)
            passed = bool(match and match.group(1).lower() == "true")
            reason_match = re.search(r"<reason>(.*?)</reason>", response.text, re.I | re.S)
            result.update({
                "semantic_pass": passed,
                "reason": (reason_match.group(1).strip() if reason_match else response.text[:1000]),
                "judge_prompt_tokens": response.prompt_tokens,
                "judge_completion_tokens": response.completion_tokens,
            })
        except Exception as exc:
            result.update({"semantic_pass": False, "reason": f"judge_error:{type(exc).__name__}"})
        return result

    judged: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(judge, item) for item in rows]
        for future in concurrent.futures.as_completed(futures):
            item = future.result()
            judged.append(item)
            print(json.dumps({k: item.get(k) for k in ("arm", "case", "input_id", "semantic_pass")}, ensure_ascii=False), flush=True)
    judged.sort(key=lambda item: (item["arm"], item["case"], item["input_id"]))
    summary: Dict[str, Any] = {}
    for arm in sorted({item["arm"] for item in judged}):
        arm_rows = [item for item in judged if item["arm"] == arm]
        cases = sorted({item["case"] for item in arm_rows})
        summary[arm] = {
            "trials": len(arm_rows),
            "semantic_pass": sum(bool(item["semantic_pass"]) for item in arm_rows),
            "three_input_task_pass": sum(
                len([item for item in arm_rows if item["case"] == case]) == 3
                and all(item["semantic_pass"] for item in arm_rows if item["case"] == case)
                for case in cases
            ),
            "judge_prompt_tokens": sum(int(item.get("judge_prompt_tokens", 0)) for item in arm_rows),
            "judge_completion_tokens": sum(int(item.get("judge_completion_tokens", 0)) for item in arm_rows),
        }
    payload = {"protocol": "official Resolve prompt with same-model low-cost judge; output capped at 16000 chars", "summary": summary, "results": judged}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
