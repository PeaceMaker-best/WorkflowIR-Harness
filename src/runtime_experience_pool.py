#!/usr/bin/env python3
"""Task-scoped runtime repair memory with no answer or raw-trace storage."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Iterable

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,63}")
SECRET_RE = re.compile(r"(?i)(bearer\s+\S+|api[_-]?key\s*[:=]\s*\S+|(?:sk|ak)-[A-Za-z0-9_-]{12,})")
URL_RE = re.compile(r"https?://\S+")
STOP = {"the", "and", "for", "with", "from", "this", "that", "failed", "failure", "error", "execution", "node", "workflow"}
KNOWN_NODE_TYPES = {"start", "end", "llm", "code", "http-request", "iteration", "variable-aggregator", "question-classifier", "document-extractor", "parameter-extractor", "template-transform", "if-else", "tool"}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def safe_scope(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(value))[:96]
    if not value:
        raise ValueError("empty task scope")
    return value

def sanitize(value: Any, limit: int = 600) -> str:
    text = str(value or "")
    text = SECRET_RE.sub("[secret redacted]", text)
    text = URL_RE.sub("[url redacted]", text)
    text = re.sub(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b", "[email redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]

def tokens(value: Any) -> tuple[str, ...]:
    found = {item.lower() for item in TOKEN_RE.findall(sanitize(value, 3000))}
    return tuple(sorted(item for item in found if item not in STOP))[:96]

def graph_types(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(item).strip().lower() for item in values if str(item).strip()}))

def similarity(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def reliability(success: int, failure: int) -> float:
    total = success + failure
    if total == 0:
        return 0.0
    z = 1.96
    p = success / total
    return max(0.0, (p + z*z/(2*total) - z*math.sqrt((p*(1-p)+z*z/(4*total))/total)) / (1+z*z/total))

def extract_node_type(trace: Any) -> str:
    ranked: list[tuple[int, str]] = []
    def walk(value: Any, failed: bool = False) -> None:
        if isinstance(value, dict):
            state = str(value.get("status") or value.get("state") or "").lower()
            current_failed = failed or state in {"failed", "error", "stopped"}
            for key in ("node_type", "type"):
                candidate = str(value.get(key) or "").lower()
                if candidate in KNOWN_NODE_TYPES:
                    ranked.append((2 if current_failed else 1, candidate))
            for child in value.values():
                walk(child, current_failed)
        elif isinstance(value, list):
            for child in value:
                walk(child, failed)
    walk(trace)
    return max(ranked, default=(0, "unknown"))[1]

def repair_policy(failure_class: str, node_type: str, error: Any) -> str:
    text = sanitize(error, 1200)
    missing = re.search(r"name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] is not defined", text)
    if missing:
        return f"Expose missing symbol {missing.group(1)!r} only when permitted by the sandbox, use one shared globals/locals namespace, and rerun the full graph."
    if re.search(r"syntax|indent", text, re.I):
        return f"Regenerate only the failing {node_type} node as valid Python 3, preserve its declared I/O contract, then run syntax and whole-graph checks."
    if failure_class.startswith("binding"):
        return f"Rebind the failing {node_type} selector and output type against the current schema, then revalidate every downstream reference."
    if failure_class.startswith("graph"):
        return "Rebuild the topology skeleton from the requirement contract instead of guessing a missing edge inside an invalid graph."
    return f"Repair only the failing {node_type} node from the current trace, preserve its I/O contract, then validate and rerun the whole graph."

class RuntimeExperiencePool:
    def __init__(self, path: str | Path, ttl_days: int = 90, max_per_scope: int = 128, min_error_similarity: float = 0.25, min_graph_similarity: float = 0.35) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_days = max(1, int(ttl_days))
        self.max_per_scope = max(1, int(max_per_scope))
        self.min_error_similarity = min_error_similarity
        self.min_graph_similarity = min_graph_similarity
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS experiences (
              id TEXT PRIMARY KEY, task_scope TEXT NOT NULL, failure_class TEXT NOT NULL,
              node_type TEXT NOT NULL, error_tokens TEXT NOT NULL, graph_types TEXT NOT NULL,
              guidance TEXT NOT NULL, success_count INTEGER NOT NULL DEFAULT 0,
              failure_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL, last_used_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_scope ON experiences(task_scope, failure_class, node_type, updated_at);
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def record_success(self, task_scope: str, failure_class: str, node_type: str, graph_node_types: Iterable[str], error: Any, guidance: str | None = None) -> str:
        scope, failure, node = safe_scope(task_scope), safe_scope(failure_class), safe_scope(node_type or "unknown")
        error_tokens, signature = tokens(error), graph_types(graph_node_types)
        policy = sanitize(guidance or repair_policy(failure, node, error), 600)
        identity = json.dumps([scope, failure, node, error_tokens, signature, policy], sort_keys=True)
        item_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        stamp = now_iso()
        with self.lock, self.connect() as db:
            db.execute("""INSERT INTO experiences VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET success_count=success_count+1, updated_at=excluded.updated_at""",
            (item_id, scope, failure, node, json.dumps(error_tokens), json.dumps(signature), policy, stamp, stamp))
            db.execute("""DELETE FROM experiences WHERE task_scope=? AND id IN
            (SELECT id FROM experiences WHERE task_scope=? ORDER BY updated_at DESC LIMIT -1 OFFSET ?)""",
            (scope, scope, self.max_per_scope))
        return item_id

    def feedback(self, ids: Iterable[str], succeeded: bool) -> None:
        ids = sorted({str(item) for item in ids if item})
        if not ids:
            return
        column = "success_count" if succeeded else "failure_count"
        stamp = now_iso()
        with self.lock, self.connect() as db:
            db.executemany(f"UPDATE experiences SET {column}={column}+1, updated_at=?, last_used_at=? WHERE id=?", [(stamp, stamp, item) for item in ids])

    def retrieve(self, task_scope: str, failure_class: str, node_type: str, graph_node_types: Iterable[str], error: Any, limit: int = 2) -> list[dict[str, Any]]:
        scope, failure, node = safe_scope(task_scope), safe_scope(failure_class), safe_scope(node_type or "unknown")
        query_tokens, query_graph = tokens(error), graph_types(graph_node_types)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.ttl_days)).isoformat()
        with self.lock, self.connect() as db:
            rows = db.execute("""SELECT * FROM experiences WHERE task_scope=? AND failure_class=?
            AND (node_type=? OR node_type='unknown' OR ?='unknown') AND updated_at>=?""", (scope, failure, node, node, cutoff)).fetchall()
        ranked = []
        for row in rows:
            error_score = similarity(query_tokens, json.loads(row["error_tokens"]))
            graph_score = similarity(query_graph, json.loads(row["graph_types"]))
            if error_score < self.min_error_similarity or graph_score < self.min_graph_similarity:
                continue
            trust = reliability(row["success_count"], row["failure_count"])
            score = 0.55*error_score + 0.20*graph_score + 0.25*trust
            ranked.append({"id": row["id"], "guidance": row["guidance"], "score": round(score, 6), "error_similarity": round(error_score, 6), "graph_similarity": round(graph_score, 6), "reliability": round(trust, 6), "success_count": row["success_count"], "failure_count": row["failure_count"]})
        ranked.sort(key=lambda item: (item["score"], item["success_count"], -item["failure_count"]), reverse=True)
        selected = ranked[:max(0, int(limit))]
        if selected:
            stamp = now_iso()
            with self.lock, self.connect() as db:
                db.executemany("UPDATE experiences SET last_used_at=? WHERE id=?", [(stamp, item["id"]) for item in selected])
        return selected

    def stats(self) -> dict[str, Any]:
        with self.lock, self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
            rows = db.execute("SELECT task_scope, COUNT(*) count, SUM(success_count) successes, SUM(failure_count) failures FROM experiences GROUP BY task_scope").fetchall()
        return {"total_experiences": total, "scopes": {row["task_scope"]: {"count": row["count"], "successes": row["successes"], "failures": row["failures"]} for row in rows}}

def render_repair_context(current_error: Any, experiences: list[dict[str, Any]]) -> str:
    lines = ["CURRENT FAILURE TRACE (authoritative):", sanitize(current_error, 3000)]
    if experiences:
        lines += ["", "VERIFIED SAME-TASK REPAIR EXPERIENCES (hints only; never copy outputs):"]
        for index, item in enumerate(experiences, 1):
            lines.append(f"{index}. {item['guidance']} [score={item['score']:.3f}, success={item['success_count']}, failure={item['failure_count']}]")
    lines += ["", "Repair only the failing node, preserve declared inputs and outputs, and return no debug labels or progress text."]
    return "\n".join(lines)
