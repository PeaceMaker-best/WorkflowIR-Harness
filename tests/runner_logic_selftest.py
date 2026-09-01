#!/usr/bin/env python3
"""Pure runner-decision regression tests; no Dify or model call required."""

from pathlib import Path

import run_dify_all3 as runner
from run_dify_all3 import (
    contract_pass,
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
    print("runner_logic_selftest=PASS error_envelope=REJECTED max_repairs=2 same_task_order=SEQUENTIAL")

if __name__ == "__main__":
    main()

