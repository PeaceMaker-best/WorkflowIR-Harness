#!/usr/bin/env python3
"""Conservative self-evolving repair policies built on task-scoped experience."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from runtime_experience_pool import (
    RuntimeExperiencePool,
    graph_types,
    now_iso,
    reliability,
    repair_policy,
    safe_scope,
    sanitize,
    similarity,
    tokens,
)


class SelfEvolvingExperiencePool(RuntimeExperiencePool):
    """Promote only repeatedly verified policies and quarantine regressions."""

    def __init__(
        self,
        path: str | Path,
        ttl_days: int = 90,
        max_per_scope: int = 128,
        min_error_similarity: float = 0.25,
        min_graph_similarity: float = 0.35,
        promotion_min_successes: int = 3,
        promotion_min_reliability: float = 0.40,
        quarantine_consecutive_failures: int = 2,
    ) -> None:
        self.promotion_min_successes = max(2, int(promotion_min_successes))
        self.promotion_min_reliability = max(
            0.0, min(1.0, float(promotion_min_reliability))
        )
        self.quarantine_consecutive_failures = max(
            1, int(quarantine_consecutive_failures)
        )
        super().__init__(
            path,
            ttl_days=ttl_days,
            max_per_scope=max_per_scope,
            min_error_similarity=min_error_similarity,
            min_graph_similarity=min_graph_similarity,
        )
        self._migrate()

    def _migrate(self) -> None:
        columns = {
            "version": "INTEGER NOT NULL DEFAULT 1",
            "state": "TEXT NOT NULL DEFAULT 'candidate'",
            "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
            "parent_id": "TEXT",
            "promoted_at": "TEXT",
            "quarantined_at": "TEXT",
            "last_reason": "TEXT",
        }
        with self.lock, self.connect() as db:
            existing = {
                row["name"] for row in db.execute("PRAGMA table_info(experiences)")
            }
            for name, definition in columns.items():
                if name not in existing:
                    db.execute(
                        f"ALTER TABLE experiences ADD COLUMN {name} {definition}"
                    )
            db.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_experience_state
                  ON experiences(task_scope, failure_class, node_type, state, updated_at);
                CREATE TABLE IF NOT EXISTS experience_events (
                  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  experience_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  from_state TEXT,
                  to_state TEXT,
                  reason TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_experience_events
                  ON experience_events(experience_id, created_at);
                """
            )
            ids = [
                row["id"] for row in db.execute("SELECT id FROM experiences")
            ]
            for item_id in ids:
                self._transition_locked(db, item_id, "schema_migration")

    def _event_locked(
        self,
        db,
        item_id: str,
        event_type: str,
        from_state: str | None,
        to_state: str | None,
        reason: str,
    ) -> None:
        db.execute(
            """
            INSERT INTO experience_events(
              experience_id, event_type, from_state, to_state, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                safe_scope(event_type),
                from_state,
                to_state,
                sanitize(reason, 160),
                now_iso(),
            ),
        )

    def _transition_locked(
        self, db, item_id: str, reason: str
    ) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT * FROM experiences WHERE id=?", (item_id,)
        ).fetchone()
        if row is None:
            return None
        old_state = row["state"]
        new_state = old_state
        trust = reliability(row["success_count"], row["failure_count"])
        if old_state != "quarantined":
            if (
                row["consecutive_failures"]
                >= self.quarantine_consecutive_failures
            ):
                new_state = "quarantined"
            elif (
                old_state == "candidate"
                and row["success_count"] >= self.promotion_min_successes
                and trust >= self.promotion_min_reliability
            ):
                new_state = "active"
        transitioned = new_state != old_state
        if transitioned:
            stamp = now_iso()
            promoted_at = stamp if new_state == "active" else row["promoted_at"]
            quarantined_at = (
                stamp if new_state == "quarantined" else row["quarantined_at"]
            )
            db.execute(
                """
                UPDATE experiences
                SET state=?, promoted_at=?, quarantined_at=?,
                    last_reason=?, updated_at=?
                WHERE id=?
                """,
                (
                    new_state,
                    promoted_at,
                    quarantined_at,
                    sanitize(reason, 160),
                    stamp,
                    item_id,
                ),
            )
            self._event_locked(
                db,
                item_id,
                "policy_promoted"
                if new_state == "active"
                else "policy_quarantined",
                old_state,
                new_state,
                reason,
            )
        return {
            "id": item_id,
            "from_state": old_state,
            "to_state": new_state,
            "transitioned": transitioned,
            "success_count": row["success_count"],
            "failure_count": row["failure_count"],
            "reliability": round(trust, 6),
        }

    def get(self, item_id: str) -> dict[str, Any] | None:
        with self.lock, self.connect() as db:
            row = db.execute(
                "SELECT * FROM experiences WHERE id=?", (str(item_id),)
            ).fetchone()
        return dict(row) if row is not None else None

    def record_success(
        self,
        task_scope: str,
        failure_class: str,
        node_type: str,
        graph_node_types: Iterable[str],
        error: Any,
        guidance: str | None = None,
    ) -> str:
        """Record one whole-graph verified repair without double counting."""
        scope = safe_scope(task_scope)
        failure = safe_scope(failure_class)
        node = safe_scope(node_type or "unknown")
        error_tokens = tokens(error)
        signature = graph_types(graph_node_types)
        policy = sanitize(
            guidance or repair_policy(failure, node, error), 600
        )
        error_json = json.dumps(error_tokens)
        graph_json = json.dumps(signature)
        stamp = now_iso()
        with self.lock, self.connect() as db:
            current = db.execute(
                """
                SELECT * FROM experiences
                WHERE task_scope=? AND failure_class=? AND node_type=?
                  AND error_tokens=? AND graph_types=? AND guidance=?
                  AND state!='quarantined'
                ORDER BY version DESC LIMIT 1
                """,
                (
                    scope,
                    failure,
                    node,
                    error_json,
                    graph_json,
                    policy,
                ),
            ).fetchone()
            if current is not None:
                item_id = current["id"]
                db.execute(
                    """
                    UPDATE experiences
                    SET success_count=success_count+1,
                        consecutive_failures=0,
                        updated_at=?,
                        last_reason='whole_graph_reverified'
                    WHERE id=?
                    """,
                    (stamp, item_id),
                )
            else:
                parent = db.execute(
                    """
                    SELECT id FROM experiences
                    WHERE task_scope=? AND failure_class=? AND node_type=?
                      AND error_tokens=? AND graph_types=? AND guidance=?
                      AND state='quarantined'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (
                        scope,
                        failure,
                        node,
                        error_json,
                        graph_json,
                        policy,
                    ),
                ).fetchone()
                version = db.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM experiences
                    WHERE task_scope=? AND failure_class=? AND node_type=?
                    """,
                    (scope, failure, node),
                ).fetchone()[0]
                identity = json.dumps(
                    [
                        scope,
                        failure,
                        node,
                        error_tokens,
                        signature,
                        policy,
                        version,
                    ],
                    sort_keys=True,
                )
                item_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
                parent_id = parent["id"] if parent is not None else None
                db.execute(
                    """
                    INSERT INTO experiences(
                      id, task_scope, failure_class, node_type,
                      error_tokens, graph_types, guidance,
                      success_count, failure_count, created_at, updated_at,
                      last_used_at, version, state, consecutive_failures,
                      parent_id, promoted_at, quarantined_at, last_reason
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, NULL,
                      ?, 'candidate', 0, ?, NULL, NULL, ?
                    )
                    """,
                    (
                        item_id,
                        scope,
                        failure,
                        node,
                        error_json,
                        graph_json,
                        policy,
                        stamp,
                        stamp,
                        version,
                        parent_id,
                        "candidate_created_from_verified_repair",
                    ),
                )
                self._event_locked(
                    db,
                    item_id,
                    "candidate_created",
                    None,
                    "candidate",
                    "whole_graph_verified",
                )
            self._transition_locked(
                db, item_id, "promotion_threshold_satisfied"
            )
            db.execute(
                """
                DELETE FROM experiences
                WHERE task_scope=? AND id IN (
                  SELECT id FROM experiences
                  WHERE task_scope=?
                  ORDER BY
                    CASE state
                      WHEN 'active' THEN 0
                      WHEN 'candidate' THEN 1
                      ELSE 2
                    END,
                    updated_at DESC
                  LIMIT -1 OFFSET ?
                )
                """,
                (scope, scope, self.max_per_scope),
            )
        return item_id

    def feedback(
        self, ids: Iterable[str], succeeded: bool
    ) -> list[dict[str, Any]]:
        selected = sorted({str(item) for item in ids if item})
        if not selected:
            return []
        stamp = now_iso()
        outcomes: list[dict[str, Any]] = []
        with self.lock, self.connect() as db:
            for item_id in selected:
                if succeeded:
                    db.execute(
                        """
                        UPDATE experiences
                        SET success_count=success_count+1,
                            consecutive_failures=0,
                            updated_at=?, last_used_at=?,
                            last_reason='selected_policy_succeeded'
                        WHERE id=?
                        """,
                        (stamp, stamp, item_id),
                    )
                    reason = "selected_policy_succeeded"
                else:
                    db.execute(
                        """
                        UPDATE experiences
                        SET failure_count=failure_count+1,
                            consecutive_failures=consecutive_failures+1,
                            updated_at=?, last_used_at=?,
                            last_reason='selected_policy_failed'
                        WHERE id=?
                        """,
                        (stamp, stamp, item_id),
                    )
                    reason = "selected_policy_failed"
                outcome = self._transition_locked(db, item_id, reason)
                if outcome is not None:
                    outcomes.append(outcome)
        return outcomes

    def retrieve(
        self,
        task_scope: str,
        failure_class: str,
        node_type: str,
        graph_node_types: Iterable[str],
        error: Any,
        limit: int = 2,
        include_candidates: bool = False,
    ) -> list[dict[str, Any]]:
        """Retrieve active policies; candidates are shadow-only by default."""
        scope = safe_scope(task_scope)
        failure = safe_scope(failure_class)
        node = safe_scope(node_type or "unknown")
        query_tokens = tokens(error)
        query_graph = graph_types(graph_node_types)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
        ).isoformat()
        states = ("active", "candidate") if include_candidates else ("active",)
        placeholders = ",".join("?" for _ in states)
        with self.lock, self.connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM experiences
                WHERE task_scope=? AND failure_class=?
                  AND (node_type=? OR node_type='unknown' OR ?='unknown')
                  AND updated_at>=?
                  AND state IN ({placeholders})
                """,
                (scope, failure, node, node, cutoff, *states),
            ).fetchall()
        ranked = []
        for row in rows:
            error_score = similarity(
                query_tokens, json.loads(row["error_tokens"])
            )
            graph_score = similarity(
                query_graph, json.loads(row["graph_types"])
            )
            if (
                error_score < self.min_error_similarity
                or graph_score < self.min_graph_similarity
            ):
                continue
            trust = reliability(
                row["success_count"], row["failure_count"]
            )
            candidate_penalty = 0.08 if row["state"] == "candidate" else 0.0
            score = (
                0.55 * error_score
                + 0.20 * graph_score
                + 0.25 * trust
                - candidate_penalty
            )
            ranked.append(
                {
                    "id": row["id"],
                    "guidance": row["guidance"],
                    "score": round(score, 6),
                    "error_similarity": round(error_score, 6),
                    "graph_similarity": round(graph_score, 6),
                    "reliability": round(trust, 6),
                    "success_count": row["success_count"],
                    "failure_count": row["failure_count"],
                    "state": row["state"],
                    "version": row["version"],
                    "parent_id": row["parent_id"],
                }
            )
        ranked.sort(
            key=lambda item: (
                item["state"] == "active",
                item["score"],
                item["success_count"],
                -item["failure_count"],
                item["version"],
            ),
            reverse=True,
        )
        selected = ranked[: max(0, int(limit))]
        if selected:
            stamp = now_iso()
            with self.lock, self.connect() as db:
                db.executemany(
                    "UPDATE experiences SET last_used_at=? WHERE id=?",
                    [(stamp, item["id"]) for item in selected],
                )
        return selected

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock, self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM experience_events
                ORDER BY event_id DESC LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.lock, self.connect() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM experiences"
            ).fetchone()[0]
            state_rows = db.execute(
                """
                SELECT state, COUNT(*) count
                FROM experiences GROUP BY state
                """
            ).fetchall()
            scope_rows = db.execute(
                """
                SELECT task_scope, COUNT(*) count,
                       SUM(success_count) successes,
                       SUM(failure_count) failures
                FROM experiences GROUP BY task_scope
                """
            ).fetchall()
            event_count = db.execute(
                "SELECT COUNT(*) FROM experience_events"
            ).fetchone()[0]
        return {
            "mode": "self_evolving_safe",
            "total_experiences": total,
            "states": {
                row["state"]: row["count"] for row in state_rows
            },
            "events": event_count,
            "promotion_min_successes": self.promotion_min_successes,
            "promotion_min_reliability": self.promotion_min_reliability,
            "quarantine_consecutive_failures":
                self.quarantine_consecutive_failures,
            "scopes": {
                row["task_scope"]: {
                    "count": row["count"],
                    "successes": row["successes"],
                    "failures": row["failures"],
                }
                for row in scope_rows
            },
        }


def render_evolving_repair_context(
    current_error: Any, experiences: list[dict[str, Any]]
) -> str:
    lines = [
        "CURRENT FAILURE TRACE (authoritative):",
        sanitize(current_error, 3000),
    ]
    if experiences:
        lines += [
            "",
            "PROMOTED SAME-TASK REPAIR POLICIES "
            "(hints only; never copy outputs):",
        ]
        for index, item in enumerate(experiences, 1):
            lines.append(
                f"{index}. {item['guidance']} "
                f"[v{item['version']}, score={item['score']:.3f}, "
                f"success={item['success_count']}, "
                f"failure={item['failure_count']}]"
            )
    lines += [
        "",
        "Repair only the failing node, preserve declared inputs and outputs, "
        "and return no debug labels or progress text.",
    ]
    return "\n".join(lines)
