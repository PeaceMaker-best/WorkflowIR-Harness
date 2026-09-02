#!/usr/bin/env python3
"""Pure runner-decision regression tests; no Dify or model call required."""

from pathlib import Path

import run_dify_all3 as runner
from run_dify_all3 import (
    contract_pass,
    partition_jobs_for_resume,
    runtime_error_from_outputs,
    should_schedule_repair,
)


def main() -> None:
    error = runtime_error_from_outputs({"answer": "Execution failed: NameError"})
    assert error is not None
    assert not contract_pass(["answer"], error)
    assert contract_pass(["answer"], None)
    assert not contract_pass(None, None)
    assert should_schedule_repair(True, 1)
    assert should_schedule_repair(True, 2)
    assert not should_schedule_repair(True, 3)
    assert not should_schedule_repair(False, 1)

    uploaded = []
    original_upload_file = runner.upload_file

    def fake_upload_file(api_key, user, name):
        uploaded.append(name)
        return {"transfer_method": "local_file", "upload_file_id": name, "type": "document"}

    runner.upload_file = fake_upload_file
    try:
        prepared = runner.prepare_inputs(
            {"resume_files": [{"value": "a.pdf"}, {"value": "b.pdf"}]},
            {"resume_files": "file-list"},
            "test-key",
            "test-user",
        )
    finally:
        runner.upload_file = original_upload_file
    assert uploaded == ["a.pdf", "b.pdf"]
    assert [item["upload_file_id"] for item in prepared["resume_files"]] == ["a.pdf", "b.pdf"]

    seen = []
    original_run_one = runner.run_one

    def fake_run_one(arm, case, path, check, **kwargs):
        seen.append(case)
        return {}

    runner.run_one = fake_run_one
    try:
        grouped = runner.run_case_group(
            [
                ("ours", "Code_2", "test1", Path("one.yaml"), {}),
                ("ours", "Code_2", "test2", Path("two.yaml"), {}),
            ],
            model_provider="test",
            model_name="test",
            thinking_mode="off",
            experience_pool=None,
        )
    finally:
        runner.run_one = original_run_one
    assert seen == ["Code_2__test1", "Code_2__test2"]
    assert [item["input_id"] for item in grouped] == ["test1", "test2"]

    jobs = [
        ("staged", "Code_2", "test1", Path("one.yaml"), {}),
        ("staged", "Code_2", "test2", Path("two.yaml"), {}),
    ]
    pending, reused = partition_jobs_for_resume(
        jobs,
        [
            {"arm": "staged", "case": "Code_2", "input_id": "test1", "resolve_proxy": True},
            {"arm": "staged", "case": "Code_2", "input_id": "test2", "resolve_proxy": False},
        ],
        Path("previous/result.json"),
    )
    assert [item[2] for item in pending] == ["test2"]
    assert [item["input_id"] for item in reused] == ["test1"]
    assert reused[0]["reused_from"] == "previous/result.json"
    print("runner_logic_selftest=PASS error_envelope=REJECTED max_repairs=2 same_task_order=SEQUENTIAL")

if __name__ == "__main__":
    main()

