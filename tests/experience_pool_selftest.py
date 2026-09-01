#!/usr/bin/env python3
"""Offline regression tests for the task-scoped runtime experience pool."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path

from runtime_experience_pool import (
    RuntimeExperiencePool,
    extract_node_type,
    render_repair_context,
)

def main() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "experiences.sqlite3"
        pool = RuntimeExperiencePool(path)
        error = "Execution failed: NameError: name 'iter' is not defined; Bearer sk-example-secret-value"
        graph = ["start", "llm", "code", "iteration", "variable-aggregator", "end"]
        assert pool.retrieve(
            "Code_2", "execution_node", "code", graph,
            "NameError: name 'iter' is not defined"
        ) == []

        item_id = pool.record_success(
            "Code_2", "execution_node", "code", graph, error
        )
        exact = pool.retrieve(
            "Code_2", "execution_node", "code", graph,
            "NameError: name 'iter' is not defined", limit=2
        )
        assert len(exact) == 1 and exact[0]["id"] == item_id
        assert exact[0]["error_similarity"] > 0.25
        assert pool.retrieve(
            "Code_3", "execution_node", "code", graph,
            "NameError: name 'iter' is not defined"
        ) == []
        assert pool.retrieve(
            "Code_2", "binding_output_contract", "code", graph,
            "NameError: name 'iter' is not defined"
        ) == []
        assert pool.retrieve(
            "Code_2", "execution_node", "code", ["start", "http-request", "end"],
            "NameError: name 'iter' is not defined"
        ) == []
        pool.feedback([item_id], succeeded=True)
        pool.feedback([item_id], succeeded=False)
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(
                lambda _: pool.record_success(
                    "Code_2", "execution_node", "code", graph, error
                ),
                range(8),
            ))
        refreshed = pool.retrieve(
            "Code_2", "execution_node", "code", graph,
            "NameError: name 'iter' is not defined"
        )
        assert refreshed[0]["success_count"] == 10
        assert refreshed[0]["failure_count"] == 1
        context = render_repair_context(
            "NameError: name 'iter' is not defined", refreshed
        )
        assert "VERIFIED SAME-TASK" in context
        assert "sk-example-secret-value" not in context
        assert extract_node_type({
            "nodes": [
                {"status": "succeeded", "node_type": "llm"},
                {"status": "failed", "node_type": "code"},
            ]
        }) == "code"
        raw = path.read_bytes()
        assert b"sk-example-secret-value" not in raw
        with sqlite3.connect(path) as db:
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(experiences)")
            }
        assert "raw_trace" not in columns and "model_output" not in columns
        stats = pool.stats()
        assert stats["total_experiences"] == 1
        assert stats["scopes"]["Code_2"]["successes"] == 10
    print("experience_pool_selftest=PASS cold_hits=0 warm_hits=1 task_isolation=PASS secret_storage=PASS concurrency=PASS")

if __name__ == "__main__":
    main()
