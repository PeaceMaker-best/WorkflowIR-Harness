#!/usr/bin/env python3
"""Deterministic regression for promotion, quarantine, lineage, and migration."""
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_experience_pool import RuntimeExperiencePool
from self_evolving_pool import (
    SelfEvolvingExperiencePool,
    render_evolving_repair_context,
)


def main() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "evolving.sqlite3"
        pool = SelfEvolvingExperiencePool(path)
        error = (
            "Execution failed: NameError: name 'iter' is not defined; "
            "Bearer sk-example-secret-value"
        )
        query_error = "NameError: name 'iter' is not defined"
        graph = [
            "start",
            "llm",
            "code",
            "iteration",
            "variable-aggregator",
            "end",
        ]

        assert pool.retrieve(
            "Code_2", "execution_node", "code", graph, query_error
        ) == []

        first_id = pool.record_success(
            "Code_2", "execution_node", "code", graph, error
        )
        first = pool.get(first_id)
        assert first is not None
        assert first["state"] == "candidate"
        assert first["version"] == 1
        assert pool.retrieve(
            "Code_2", "execution_node", "code", graph, query_error
        ) == []
        shadow = pool.retrieve(
            "Code_2",
            "execution_node",
            "code",
            graph,
            query_error,
            include_candidates=True,
        )
        assert len(shadow) == 1 and shadow[0]["state"] == "candidate"

        assert pool.record_success(
            "Code_2", "execution_node", "code", graph, error
        ) == first_id
        assert pool.record_success(
            "Code_2", "execution_node", "code", graph, error
        ) == first_id
        promoted = pool.get(first_id)
        assert promoted is not None and promoted["state"] == "active"
        active = pool.retrieve(
            "Code_2", "execution_node", "code", graph, query_error
        )
        assert len(active) == 1 and active[0]["id"] == first_id
        assert active[0]["version"] == 1

        first_failure = pool.feedback([first_id], succeeded=False)
        assert first_failure[0]["to_state"] == "active"
        second_failure = pool.feedback([first_id], succeeded=False)
        assert second_failure[0]["to_state"] == "quarantined"
        assert second_failure[0]["transitioned"]
        assert pool.retrieve(
            "Code_2", "execution_node", "code", graph, query_error
        ) == []

        second_id = pool.record_success(
            "Code_2", "execution_node", "code", graph, error
        )
        assert second_id != first_id
        second = pool.get(second_id)
        assert second is not None
        assert second["state"] == "candidate"
        assert second["version"] == 2
        assert second["parent_id"] == first_id
        pool.record_success(
            "Code_2", "execution_node", "code", graph, error
        )
        pool.record_success(
            "Code_2", "execution_node", "code", graph, error
        )
        replacement = pool.retrieve(
            "Code_2", "execution_node", "code", graph, query_error
        )
        assert len(replacement) == 1
        assert replacement[0]["id"] == second_id
        assert replacement[0]["version"] == 2
        assert replacement[0]["state"] == "active"

        assert pool.retrieve(
            "Code_3", "execution_node", "code", graph, query_error
        ) == []
        assert pool.retrieve(
            "Code_2",
            "binding_output_contract",
            "code",
            graph,
            query_error,
        ) == []
        assert pool.retrieve(
            "Code_2",
            "execution_node",
            "code",
            ["start", "http-request", "end"],
            query_error,
        ) == []

        context = render_evolving_repair_context(query_error, replacement)
        assert "PROMOTED SAME-TASK" in context
        assert "[v2," in context
        assert "sk-example-secret-value" not in context
        assert b"sk-example-secret-value" not in path.read_bytes()

        stats = pool.stats()
        assert stats["mode"] == "self_evolving_safe"
        assert stats["states"] == {"active": 1, "quarantined": 1}
        assert stats["events"] >= 5
        events = pool.events()
        assert any(
            event["event_type"] == "policy_promoted" for event in events
        )
        assert any(
            event["event_type"] == "policy_quarantined" for event in events
        )
        with closing(sqlite3.connect(path)) as db:
            columns = {
                row[1] for row in db.execute(
                    "PRAGMA table_info(experiences)"
                )
            }
        assert {
            "version",
            "state",
            "consecutive_failures",
            "parent_id",
            "last_reason",
        }.issubset(columns)

        legacy_path = Path(directory) / "legacy.sqlite3"
        legacy = RuntimeExperiencePool(legacy_path)
        legacy_id = ""
        for _ in range(3):
            legacy_id = legacy.record_success(
                "Code_1",
                "execution_node",
                "code",
                ["start", "code", "end"],
                "SyntaxError: invalid syntax",
            )
        migrated = SelfEvolvingExperiencePool(legacy_path)
        migrated_item = migrated.get(legacy_id)
        assert migrated_item is not None
        assert migrated_item["state"] == "active"
        legacy_after_migration = RuntimeExperiencePool(legacy_path)
        assert legacy_after_migration.record_success(
            "Code_1",
            "execution_node",
            "code",
            ["start", "code", "end"],
            "SyntaxError: invalid syntax",
        ) == legacy_id
        assert migrated.get(legacy_id)["success_count"] == 4

    print(
        "self_evolving_pool_selftest=PASS "
        "candidate_shadow=PASS promotion=PASS quarantine=PASS "
        "lineage=PASS migration=PASS secret_storage=PASS"
    )


if __name__ == "__main__":
    main()
