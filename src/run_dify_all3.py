from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
import yaml

from dify_yaml_adapter import patch_runtime_contracts
from requirement_contract_repairs import apply_requirement_contract_repairs
from runtime_experience_pool import extract_node_type
from self_evolving_pool import (
    SelfEvolvingExperiencePool,
    render_evolving_repair_context,
)

REPO_ROOT = Path(__file__).resolve().parent
CONSOLE = os.environ.get("DIFY_CONSOLE_URL", "http://127.0.0.1:18081/console/api")
SERVICE = os.environ.get("DIFY_SERVICE_URL", "http://127.0.0.1:18081/v1")
ADMIN_FILE = Path(os.environ.get("DIFY_ADMIN_FILE", REPO_ROOT / ".env"))
CHECK_FILE = Path(os.environ.get("BENCH_CHECK_FILE", REPO_ROOT / "data" / "check_pass_stage.json"))
CASE_FILES = Path(os.environ.get("BENCH_CASE_FILES", REPO_ROOT / "data" / "case_files"))
RESULT_DIR = Path(os.environ.get("HARNESS_RESULT_DIR", REPO_ROOT / "results"))
ARMS = {
    "baseline": Path(os.environ.get("BASELINE_YAML_DIR", REPO_ROOT / "examples" / "baseline")),
    "staged": Path(os.environ.get("STAGED_YAML_DIR", REPO_ROOT / "examples" / "harness")),
}
MAX_WORKERS = 26
DEFAULT_PROVIDER = "langgenius/openai_api_compatible/openai_api_compatible"
DEFAULT_MODEL = "doubao-seed-evolving"


def load_env(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def login() -> requests.Session:
    credentials = load_env(ADMIN_FILE)
    session = requests.Session()
    response = session.post(
        f"{CONSOLE}/login",
        json={
            "email": credentials["DIFY_SMOKE_ADMIN_EMAIL"],
            "password": credentials["DIFY_SMOKE_ADMIN_PASSWORD"],
        },
        timeout=30,
    )
    response.raise_for_status()
    csrf = session.cookies.get("csrf_token")
    if csrf:
        session.headers.update({"X-CSRF-Token": csrf})
    return session


def normalize_dsl(
    path: Path,
    arm: str,
    case: str,
    model_provider: str = DEFAULT_PROVIDER,
    model_name: str = DEFAULT_MODEL,
    thinking_mode: str = "disabled",
) -> Tuple[str, Dict[str, str], List[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # The low-cost harness validates the generated graph itself. Marketplace
    # installation is an environment concern and is recorded at runtime.
    data["dependencies"] = []
    data.setdefault("app", {})["name"] = f"harness_{arm}_{case}"
    start_types: Dict[str, str] = {}
    for node in data.get("workflow", {}).get("graph", {}).get("nodes", []):
        node_data = node.get("data") or {}
        if node_data.get("type") == "start":
            for variable in node_data.get("variables", []):
                start_types[str(variable.get("variable"))] = str(variable.get("type", "paragraph"))
    requirement_actions = (
        apply_requirement_contract_repairs(data) if arm in {"ours", "staged", "harness"} else []
    )
    if any(action.startswith("add_trace_repair_channel:") for action in requirement_actions):
        start_types["repair_hint"] = "paragraph"
    runtime_actions = patch_runtime_contracts(
        data,
        model_provider=model_provider,
        model_name=model_name,
        thinking_mode=thinking_mode,
        max_iteration_items=max(1, int(os.environ.get("HARNESS_MAX_ITERATION_ITEMS", "12"))),
    )
    adapter_actions = requirement_actions + runtime_actions
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False), start_types, adapter_actions


def import_publish(session: requests.Session, yaml_content: str) -> Dict[str, Any]:
    response = session.post(
        f"{CONSOLE}/apps/imports",
        json={"mode": "yaml-content", "yaml_content": yaml_content},
        timeout=120,
    )
    status = response.status_code
    response.raise_for_status()
    payload = response.json()
    confirm_status = None
    if status == 202:
        confirm = session.post(f"{CONSOLE}/apps/imports/{payload['id']}/confirm", json={}, timeout=120)
        confirm_status = confirm.status_code
        confirm.raise_for_status()
        app_id = str(confirm.json()["app_id"])
    else:
        app_id = str(payload["app_id"])
    publish = session.post(f"{CONSOLE}/apps/{app_id}/workflows/publish", json={}, timeout=90)
    publish.raise_for_status()
    return {"app_id": app_id, "import_status": status, "confirm_status": confirm_status, "publish_status": publish.status_code}


def create_key(session: requests.Session, app_id: str) -> Tuple[str, str]:
    response = session.post(f"{CONSOLE}/apps/{app_id}/api-keys", json={}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return str(payload["id"]), str(payload["token"])


def delete_key(session: requests.Session, app_id: str, key_id: str) -> int:
    response = session.delete(f"{CONSOLE}/apps/{app_id}/api-keys/{key_id}", timeout=30)
    if response.status_code != 204:
        response.raise_for_status()
    return response.status_code


def read_case_file(name: str) -> str:
    path = (CASE_FILES / name).resolve()
    if CASE_FILES.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError(name)
    return path.read_text(encoding="utf-8", errors="replace")


def upload_file(api_key: str, user: str, name: str) -> Dict[str, Any]:
    path = (CASE_FILES / name).resolve()
    if CASE_FILES.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError(name)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as handle:
        response = requests.post(
            f"{SERVICE}/files/upload",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"user": user},
            files={"file": (path.name, handle, mime)},
            timeout=90,
        )
    response.raise_for_status()
    payload = response.json()
    file_type = ("image" if mime.startswith("image/") else "audio" if mime.startswith("audio/") else "video" if mime.startswith("video/") else "document")
    return {"transfer_method": "local_file", "upload_file_id": payload["id"], "type": file_type}


def prepare_inputs(raw: Dict[str, Any], start_types: Dict[str, str], api_key: str, user: str) -> Dict[str, Any]:
    prepared: Dict[str, Any] = {}
    for name, value in raw.items():
        variable_type = start_types.get(name, "paragraph")
        if isinstance(value, list) and variable_type in {"file-list", "multiple-files"}:
            uploaded_files: List[Dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("value"), str):
                    uploaded_files.append(upload_file(api_key, user, item["value"]))
                elif (
                    isinstance(item, dict)
                    and item.get("transfer_method") == "local_file"
                    and item.get("upload_file_id")
                ):
                    uploaded_files.append(item)
                else:
                    raise TypeError(
                        f"Unsupported file-list item for {name}: {type(item).__name__}"
                    )
            prepared[name] = uploaded_files
            continue
        if value == "" and variable_type in {"file", "single-file", "file-list", "multiple-files"}:
            continue
        if isinstance(value, dict) and isinstance(value.get("value"), str):
            file_name = value["value"]
            variable_type = start_types.get(name, "paragraph")
            if variable_type in {"file-list", "multiple-files"}:
                prepared[name] = [upload_file(api_key, user, file_name)]
            elif variable_type in {"file", "single-file"}:
                prepared[name] = upload_file(api_key, user, file_name)
            else:
                prepared[name] = read_case_file(file_name)
        else:
            prepared[name] = value
    return prepared


def trace_for(session: requests.Session, app_id: str, run_id: str) -> Dict[str, Any]:
    detail = session.get(f"{CONSOLE}/apps/{app_id}/workflow-runs/{run_id}", timeout=30)
    nodes = session.get(f"{CONSOLE}/apps/{app_id}/workflow-runs/{run_id}/node-executions", timeout=30)
    return {
        "detail": detail.json() if detail.ok else {"http_status": detail.status_code},
        "node_executions": nodes.json() if nodes.ok else {"http_status": nodes.status_code},
    }


def nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return value is not None


def expected_configs(value: Any) -> List[List[str]]:
    if isinstance(value, list) and value and all(isinstance(item, list) for item in value):
        return [[str(name) for name in item] for item in value]
    if isinstance(value, list):
        return [[str(name) for name in value]]
    return [[]]


def github_rate_preflight(jobs: List[Tuple[Any, ...]], disabled: bool = False) -> Dict[str, Any]:
    github_jobs = [job for job in jobs if str(job[1]).startswith("GithubSummary_")]
    if disabled or not github_jobs:
        return {"checked": False, "reason": "disabled" if disabled else "no_github_jobs"}

    estimated_requests = 0
    for _, _, yaml_path, _ in github_jobs:
        workflow = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
        nodes = workflow.get("workflow", {}).get("graph", {}).get("nodes", [])
        estimated_requests += sum(
            1 for node in nodes if (node.get("data") or {}).get("type") == "http-request"
        )
    # Reserve one retry budget. This avoids launching a batch that will become
    # invalid halfway through because anonymous GitHub quota is exhausted.
    required_requests = max(1, estimated_requests * 2)
    try:
        response = requests.get(
            "https://api.github.com/rate_limit",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "chat2workflow-harness"},
            timeout=15,
        )
        response.raise_for_status()
        core = (response.json().get("resources") or {}).get("core") or {}
        remaining = int(core.get("remaining", -1))
        reset_epoch = int(core.get("reset", 0))
    except (requests.RequestException, TypeError, ValueError) as exc:
        raise SystemExit(f"GitHub rate-limit preflight failed: {exc!r}") from exc

    reset_at = (
        datetime.fromtimestamp(reset_epoch, tz=timezone.utc).isoformat()
        if reset_epoch
        else None
    )
    preflight = {
        "checked": True,
        "jobs": len(github_jobs),
        "estimated_requests": estimated_requests,
        "required_with_retry_reserve": required_requests,
        "remaining": remaining,
        "reset_at_utc": reset_at,
    }
    if remaining < required_requests:
        raise SystemExit(
            "GitHub quota preflight aborted the batch before Dify execution: "
            f"remaining={remaining}, required={required_requests}, reset_at_utc={reset_at}"
        )
    return preflight


def classify_failure(error: Any, trace: Dict[str, Any] | None) -> str:
    error_text = json.dumps(error, ensure_ascii=False).lower()
    trace_text = json.dumps(trace, ensure_ascii=False).lower()
    combined = f"{error_text} {trace_text}"
    if re.search(r"readtimeout|connecttimeout|timed? ?out|timeout", error_text):
        return "infrastructure_timeout"
    if re.search(r"sandbox.*401|401.*sandbox|code execution.*401|status code 401", error_text):
        return "infrastructure_sandbox"
    if re.search(r"credential|provider|model.*not|not.*model|rate.?limit|too many requests", error_text):
        return "infrastructure_model"
    if re.search(r"pluginnotfound|plugin not found|tool.*not found|not found.*tool", combined):
        return "infrastructure_plugin"
    if re.search(r"(?:import|yaml|dsl).*(?:fail|error|invalid)|(?:fail|error|invalid).*(?:import|yaml|dsl)", error_text):
        return "adapter_import"
    return "execution_node"

def runtime_error_from_outputs(outputs: Dict[str, Any]) -> str | None:
    return next(
        (
            value
            for value in outputs.values()
            if isinstance(value, str) and "execution failed" in value.lower()
        ),
        None,
    )


def contract_pass(matched_config: List[str] | None, runtime_error: str | None) -> bool:
    """A populated error envelope is not a valid business output."""
    return matched_config is not None and runtime_error is None

def should_schedule_repair(directed_repair: bool, attempt: int, max_attempts: int = 3) -> bool:
    return bool(directed_repair and attempt < max_attempts)




def run_one(
    arm: str,
    case: str,
    yaml_path: Path,
    check: Dict[str, Any],
    model_provider: str = DEFAULT_PROVIDER,
    model_name: str = DEFAULT_MODEL,
    thinking_mode: str = "disabled",
    experience_pool: SelfEvolvingExperiencePool | None = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"arm": arm, "case": case, "thread": threading.current_thread().name}
    session: requests.Session | None = None
    app_id = key_id = api_key = None
    try:
        yaml_content, start_types, adapter_actions = normalize_dsl(
            yaml_path,
            arm,
            case,
            model_provider=model_provider,
            model_name=model_name,
            thinking_mode=thinking_mode,
        )
        workflow_document = yaml.safe_load(yaml_content)
        graph_node_types = [
            str((node.get("data") or {}).get("type") or "unknown")
            for node in workflow_document.get("workflow", {}).get("graph", {}).get("nodes", [])
        ]
        task_scope = case.split("__", 1)[0]
        result["experience_pool_enabled"] = experience_pool is not None
        result["experience_scope"] = task_scope
        result["experience_retrievals"] = []
        result["experience_learned_ids"] = []
        result["experience_learned"] = []
        result["experience_feedback"] = []
        result["experience_transitions"] = []

        result["adapter_actions"] = adapter_actions
        session = login()
        setup = import_publish(session, yaml_content)
        result["setup"] = setup
        app_id = setup["app_id"]
        key_id, api_key = create_key(session, app_id)
        user = f"parallel-{arm}-{case}"
        inputs = prepare_inputs(check["test1"], start_types, api_key, user)
        configs = expected_configs(check.get("output_var", []))
        attempts: List[Dict[str, Any]] = []
        transient_tool_failure = False
        model_rate_limited = False
        pending_learning: Dict[str, Any] | None = None
        pending_experience_ids: List[str] = []
        effective_output_contract_pass = False
        current_failure_class: str | None = None
        for attempt in range(1, 4):
            response = requests.post(
                f"{SERVICE}/workflows/run",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"inputs": inputs, "response_mode": "blocking", "user": user},
                timeout=240,
            )
            payload = response.json() if response.content else {}
            data = payload.get("data") or {}
            outputs = data.get("outputs") or {}
            run_id = payload.get("workflow_run_id") or data.get("id")
            execution_pass = response.status_code == 200 and data.get("status") == "succeeded"
            matched_config = next(
                (config for config in configs if all(name in outputs and nonempty(outputs[name]) for name in config)),
                None,
            )
            trace = trace_for(session, app_id, str(run_id)) if run_id else None
            trace_text = json.dumps(trace, ensure_ascii=False).lower()
            transient_tool_failure = bool(re.search(
                r"(?:conversion failed:\s*)?http 5\d\d|too many clients|sqlstate 53300|plugindaemoninternalservererror",
                trace_text,
            ))
            model_rate_limited = bool(re.search(r"status[_ ]code.{0,3}429|tpm.*limit|too many requests|model .{0,120} not exist", trace_text))
            runtime_error_output = runtime_error_from_outputs(outputs)
            directed_repair = bool(arm in {"ours", "staged", "harness"} and "repair_hint" in start_types and runtime_error_output)
            effective_output_contract_pass = contract_pass(matched_config, runtime_error_output)
            if execution_pass and effective_output_contract_pass:
                current_failure_class = None
            elif transient_tool_failure:
                current_failure_class = "infrastructure_tool_transient"
            elif model_rate_limited:
                current_failure_class = "infrastructure_model"
            elif runtime_error_output:
                current_failure_class = "execution_node"
            elif execution_pass:
                current_failure_class = "binding_output_contract"
            else:
                current_failure_class = classify_failure(data.get("error") or payload, trace)

            recovered = execution_pass and effective_output_contract_pass
            if (
                experience_pool is not None
                and recovered
                and pending_learning is not None
            ):
                if pending_experience_ids:
                    outcomes = experience_pool.feedback(
                        pending_experience_ids, succeeded=True
                    )
                    result["experience_feedback"].extend(outcomes)
                    result["experience_transitions"].extend(
                        item for item in outcomes if item["transitioned"]
                    )
                else:
                    learned_id = experience_pool.record_success(
                        **pending_learning
                    )
                    learned = experience_pool.get(learned_id)
                    result["experience_learned_ids"].append(learned_id)
                    if learned is not None:
                        result["experience_learned"].append(
                            {
                                "id": learned_id,
                                "state": learned["state"],
                                "version": learned["version"],
                            }
                        )
                pending_learning = None
                pending_experience_ids = []
            elif (
                experience_pool is not None
                and pending_experience_ids
                and not transient_tool_failure
                and not model_rate_limited
            ):
                outcomes = experience_pool.feedback(
                    pending_experience_ids, succeeded=False
                )
                result["experience_feedback"].extend(outcomes)
                result["experience_transitions"].extend(
                    item for item in outcomes if item["transitioned"]
                )
                pending_learning = None
                pending_experience_ids = []

            repair_scheduled = should_schedule_repair(directed_repair, attempt)
            retrieved_experiences: List[Dict[str, Any]] = []
            if repair_scheduled:
                failing_node_type = extract_node_type(trace)
                if experience_pool is not None:
                    retrieved_experiences = experience_pool.retrieve(
                        task_scope, current_failure_class or "execution_node",
                        failing_node_type, graph_node_types, runtime_error_output, limit=1,
                    )
                pending_experience_ids = [item["id"] for item in retrieved_experiences]
                result["experience_retrievals"].append({
                    "attempt": attempt,
                    "ids": pending_experience_ids,
                    "scores": [item["score"] for item in retrieved_experiences],
                    "states": [item["state"] for item in retrieved_experiences],
                    "versions": [item["version"] for item in retrieved_experiences],
                    "reliabilities": [item["reliability"] for item in retrieved_experiences],
                })
                pending_learning = {
                    "task_scope": task_scope, "failure_class": current_failure_class or "execution_node",
                    "node_type": failing_node_type, "graph_node_types": graph_node_types,
                    "error": runtime_error_output,
                }
            attempts.append(
                {
                    "attempt": attempt,
                    "http_status": response.status_code,
                    "status": data.get("status"),
                    "execution_pass": execution_pass,
                    "output_contract_pass": effective_output_contract_pass,
                    "transient_tool_failure": transient_tool_failure,
                    "model_rate_limited": model_rate_limited,
                    "directed_repair": repair_scheduled,
                    "experience_ids": pending_experience_ids if repair_scheduled else [],
                    "run_id": run_id,
                }
            )
            if repair_scheduled:
                inputs["repair_hint"] = render_evolving_repair_context(runtime_error_output, retrieved_experiences)
            retryable = transient_tool_failure or model_rate_limited or directed_repair
            if not (retryable and attempt < 3):
                break
            time.sleep(15 * attempt if model_rate_limited else 0.2 if directed_repair else 1)
        result.update(
            {
                "setup": setup,
                "http_status": response.status_code,
                "run_id": run_id,
                "status": data.get("status"),
                "error": data.get("error") or payload.get("message"),
                "elapsed_time": data.get("elapsed_time"),
                "total_steps": data.get("total_steps"),
                "output_keys": sorted(outputs),
                "execution_pass": execution_pass,
                "output_contract_pass": effective_output_contract_pass,
                "resolve_proxy": bool(execution_pass and effective_output_contract_pass),
                "matched_output_config": matched_config,
                "failure_class": current_failure_class,
                "attempts": attempts,
                "directed_repair_attempts": sum(1 for item in attempts if item.get("directed_repair")),
                "trace": trace,
            }
        )
    except Exception as exc:
        result.update({"execution_pass": False, "output_contract_pass": False, "resolve_proxy": False, "error": repr(exc), "failure_class": classify_failure(repr(exc), None)})
    finally:
        if session is not None and app_id and key_id:
            try:
                result["api_key_delete_status"] = delete_key(session, app_id, key_id)
            except Exception as exc:
                result["api_key_delete_error"] = repr(exc)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a targeted, low-cost Dify execution A/B.")
    parser.add_argument("--arm", dest="arms", action="append", choices=sorted(ARMS))
    parser.add_argument("--case", dest="cases", action="append")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking", choices=("disabled", "enabled"), default="disabled")
    parser.add_argument("--result-dir", default=str(RESULT_DIR))
    parser.add_argument("--skip-external-preflight", action="store_true")
    args = parser.parse_args()

    result_dir = Path(args.result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    checks = json.loads(CHECK_FILE.read_text(encoding="utf-8"))
    selected_arms = args.arms or list(ARMS)
    selected_cases = set(args.cases or [])
    jobs = []
    for arm in selected_arms:
        directory = ARMS[arm]
        for path in sorted(directory.glob("*.yaml")):
            case = path.stem
            if case in checks and (not selected_cases or case in selected_cases):
                jobs.append((arm, case, path, checks[case]))

    if not jobs:
        raise SystemExit("No matching jobs.")

    external_preflight = github_rate_preflight(jobs, disabled=args.skip_external_preflight)
    if external_preflight.get("checked"):
        print(json.dumps({"external_preflight": external_preflight}, ensure_ascii=False), flush=True)

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers), thread_name_prefix="dify-ab") as pool:
        futures = {
            pool.submit(
                run_one,
                *job,
                model_provider=args.provider,
                model_name=args.model,
                thinking_mode=args.thinking,
            ): job[:2]
            for job in jobs
        }
        for future in as_completed(futures):
            item = future.result()
            results.append(item)
            print(
                json.dumps(
                    {
                        key: item.get(key)
                        for key in ("arm", "case", "status", "execution_pass", "resolve_proxy", "failure_class")
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    results.sort(key=lambda item: (item["arm"], item["case"]))
    summary: Dict[str, Any] = {
        "protocol": "custom low-cost protocol: one frozen artifact and test1 only",
        "workers": max(1, args.workers),
        "model_provider": args.provider,
        "model": args.model,
        "thinking": args.thinking,
        "external_preflight": external_preflight,
        "arms": {},
    }
    for arm in selected_arms:
        rows = [item for item in results if item["arm"] == arm]
        summary["arms"][arm] = {
            "cases": len(rows),
            "execution_pass": sum(bool(item.get("execution_pass")) for item in rows),
            "resolve_proxy": sum(bool(item.get("resolve_proxy")) for item in rows),
            "failure_classes": {
                name: sum(item.get("failure_class") == name for item in rows)
                for name in sorted({item.get("failure_class") for item in rows if item.get("failure_class")})
            },
        }
    payload = {"summary": summary, "results": results}
    (result_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Developer low-cost targeted Dify A/B",
        "",
        "One frozen generated artifact and the first fixed input per case.",
        "",
        "| Arm | Cases | Execution pass | Resolve proxy |",
        "|---|---:|---:|---:|",
    ]
    for arm, value in summary["arms"].items():
        lines.append(f"| {arm} | {value['cases']} | {value['execution_pass']} | {value['resolve_proxy']} |")
    lines.extend(["", "## Cases", ""])
    for item in results:
        lines.append(
            f"- {item['arm']} / {item['case']}: status={item.get('status')}, "
            f"execution={item.get('execution_pass')}, resolve={item.get('resolve_proxy')}, "
            f"failure={item.get('failure_class')}"
        )
    (result_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))



def run_case_group(
    group: List[Tuple[str, str, str, Path, Dict[str, Any]]],
    model_provider: str,
    model_name: str,
    thinking_mode: str,
    experience_pool: SelfEvolvingExperiencePool | None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for arm, case, input_id, path, check in group:
        item = run_one(
            arm,
            f"{case}__{input_id}",
            path,
            check,
            model_provider=model_provider,
            model_name=model_name,
            thinking_mode=thinking_mode,
            experience_pool=experience_pool,
        )
        item["case"] = case
        item["input_id"] = input_id
        results.append(item)
    return results


def partition_jobs_for_resume(
    jobs: List[Tuple[str, str, str, Path, Dict[str, Any]]],
    previous_rows: List[Dict[str, Any]],
    source: Path,
) -> Tuple[List[Tuple[str, str, str, Path, Dict[str, Any]]], List[Dict[str, Any]]]:
    previous = {
        (str(item.get("arm")), str(item.get("case")), str(item.get("input_id"))): item
        for item in previous_rows
    }
    pending = []
    reused = []
    for job in jobs:
        prior = previous.get((job[0], job[1], job[2]))
        if prior and prior.get("resolve_proxy"):
            item = dict(prior)
            item["reused_from"] = str(source)
            reused.append(item)
        else:
            pending.append(job)
    return pending, reused


def main_all3() -> None:
    parser = argparse.ArgumentParser(description="Run three fixed Dify inputs per workflow.")
    parser.add_argument("--arm", dest="arms", action="append", choices=sorted(ARMS))
    parser.add_argument("--case", dest="cases", action="append")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking", choices=("disabled", "enabled"), default="disabled")
    parser.add_argument("--result-dir", required=True)
    parser.add_argument(
        "--experience-db",
        help="SQLite path for safe self-evolving runtime repair policies.",
    )
    parser.add_argument(
        "--experience-promotion-successes",
        type=int,
        default=3,
        help="Whole-graph successes required before a candidate can be used.",
    )
    parser.add_argument(
        "--experience-promotion-reliability", type=float, default=0.40,
    )
    parser.add_argument(
        "--experience-quarantine-failures",
        type=int,
        default=2,
        help="Consecutive policy failures before automatic quarantine.",
    )
    parser.add_argument(
        "--resume-from",
        help="Existing result.json. Passing trials are reused; only missing or failed trials run.",
    )
    parser.add_argument(
        "--sample-parallel",
        action="store_true",
        help="Run fixed inputs independently in parallel. Incompatible with an experience database.",
    )
    args = parser.parse_args()
    experience_pool = (
        SelfEvolvingExperiencePool(
            args.experience_db,
            promotion_min_successes=args.experience_promotion_successes,
            promotion_min_reliability=args.experience_promotion_reliability,
            quarantine_consecutive_failures=
                args.experience_quarantine_failures,
        )
        if args.experience_db
        else None
    )

    result_dir = Path(args.result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    checks = json.loads(CHECK_FILE.read_text(encoding="utf-8"))
    selected_arms = args.arms or list(ARMS)
    selected_cases = set(args.cases or [])
    jobs = []
    for arm in selected_arms:
        for path in sorted(ARMS[arm].glob("*.yaml")):
            case = path.stem
            if case not in checks or (selected_cases and case not in selected_cases):
                continue
            for input_id in ("test1", "test2", "test3"):
                if input_id not in checks[case]:
                    continue
                check = dict(checks[case])
                check["test1"] = checks[case][input_id]
                jobs.append((arm, case, input_id, path, check))
    if not jobs:
        raise SystemExit("No matching jobs.")

    if args.sample_parallel and experience_pool is not None:
        raise SystemExit(
            "--sample-parallel cannot be combined with --experience-db; "
            "warm repair order must stay sequential."
        )

    reused_results: List[Dict[str, Any]] = []
    if args.resume_from:
        resume_path = Path(args.resume_from)
        previous_rows = json.loads(
            resume_path.read_text(encoding="utf-8")
        ).get("results", [])
        jobs, reused_results = partition_jobs_for_resume(
            jobs, previous_rows, resume_path
        )
        print(json.dumps({
            "resume_from": str(resume_path),
            "reused_successes": len(reused_results),
            "scheduled_trials": len(jobs),
        }, ensure_ascii=False), flush=True)

    results: List[Dict[str, Any]] = list(reused_results)
    grouped_jobs: Dict[Tuple[str, ...], List[Tuple[str, str, str, Path, Dict[str, Any]]]] = {}
    for job in jobs:
        group_key = (job[0], job[1], job[2]) if args.sample_parallel else (job[0], job[1])
        grouped_jobs.setdefault(group_key, []).append(job)
    thread_prefix = "dify-trial" if args.sample_parallel else "dify-all3"
    with ThreadPoolExecutor(max_workers=max(1, args.workers), thread_name_prefix=thread_prefix) as pool:
        futures = {
            pool.submit(
                run_case_group,
                group,
                args.provider,
                args.model,
                args.thinking,
                experience_pool,
            ): key
            for key, group in grouped_jobs.items()
        }
        for future in as_completed(futures):
            for item in future.result():
                results.append(item)
                print(json.dumps({
                    "arm": item["arm"],
                    "case": item["case"],
                    "input": item["input_id"],
                    "execution": item.get("execution_pass"),
                    "output": item.get("output_contract_pass"),
                    "failure": item.get("failure_class"),
                }, ensure_ascii=False), flush=True)

    results.sort(key=lambda item: (item["arm"], item["case"], item["input_id"]))
    summary: Dict[str, Any] = {
        "protocol": "custom final-state protocol: one frozen workflow and three fixed inputs",
        "workers": max(1, args.workers),
        "model": args.model,
        "thinking": args.thinking,
        "experience_pool_enabled": experience_pool is not None,
        "sample_parallel": args.sample_parallel,
        "resumed_successes": len(reused_results),
        "scheduled_trials": len(jobs),
        "arms": {},
    }
    for arm in selected_arms:
        rows = [item for item in results if item["arm"] == arm]
        cases = sorted({item["case"] for item in rows})
        task_pass = sum(
            all(item.get("resolve_proxy") for item in rows if item["case"] == case)
            and len([item for item in rows if item["case"] == case]) == 3
            for case in cases
        )
        summary["arms"][arm] = {
            "workflows": len(cases),
            "trials": len(rows),
            "execution_pass": sum(bool(item.get("execution_pass")) for item in rows),
            "output_contract_pass": sum(bool(item.get("output_contract_pass")) for item in rows),
            "resolve_proxy": sum(bool(item.get("resolve_proxy")) for item in rows),
            "three_input_task_pass": task_pass,
            "failure_classes": {
                name: sum(item.get("failure_class") == name for item in rows)
                for name in sorted({item.get("failure_class") for item in rows if item.get("failure_class")})
            },
        }
    if experience_pool is not None:
        summary["experience_pool"] = experience_pool.stats()
    payload = {"summary": summary, "results": results}
    (result_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main_all3()