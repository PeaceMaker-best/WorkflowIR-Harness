# Task-scoped runtime experience pool

The experience pool reduces repeated repair cost without becoming an answer cache or leaking solutions across benchmark tasks.
The v0.2 runner wraps these base storage and retrieval mechanics with the candidate, active, and quarantined lifecycle documented in [SELF_EVOLUTION.md](SELF_EVOLUTION.md). Only promoted active policies are injected online.


## Lifecycle

1. Execute a validated workflow.
2. Detect a node-level runtime error from the trace or output error envelope.
3. Classify the failure and identify the failing node type.
4. Retrieve the top promoted policy under strict same-task gates for attributable feedback.
5. Inject the current trace as authoritative evidence and past policies as optional hints.
6. Rerun the complete graph; never accept a local repair without full-graph validation.
7. Persist a policy only when the repair produces a successful end-to-end run.

## Stored schema

| Field | Purpose |
|---|---|
| `task_scope` | Exact workflow family; cross-task recall is forbidden. |
| `failure_class` | Graph, binding, execution, or infrastructure class. |
| `node_type` | Failing Dify node type. |
| `error_tokens` | Redacted normalized signature, not the raw trace. |
| `graph_types` | Set of node types, not node content or parameters. |
| `guidance` | Generic repair policy. |
| counters | Successful and failed reuse feedback. |
| timestamps | TTL, audit, and retention controls. |

## Retrieval

Hard filters require exact task scope and failure class, a compatible node type, a non-expired record, error-token Jaccard similarity of at least 0.25, and graph-signature Jaccard similarity of at least 0.35.

Surviving records are ranked by `0.55 * error_similarity + 0.20 * graph_similarity + 0.25 * Wilson_reliability`. Negative reuse feedback lowers reliability instead of silently keeping a harmful hint.

## Safety boundary

The database never stores:

- raw user input or output;
- expected answers;
- full model responses or traces;
- credentials, URLs, or email addresses;
- node parameters or complete workflow graphs.

Infrastructure failures are retryable availability events and never become repair experience. This prevents a Dify capacity incident from teaching the model to mutate a valid workflow.

## Concurrency model

Fixed inputs within one task scope execute sequentially so a successful repair can warm the next input. Different tasks execute concurrently. SQLite WAL mode, a process lock, and bounded retention keep writes safe under the task-parallel runner.

## Validation

The offline regression observes zero cold-start hits and one verified same-task warm hit; it also verifies task isolation, wrong-class and wrong-graph rejection, redaction, concurrent feedback, and the absence of secret or raw-output columns. This is a routing and storage regression, not a claim of online task-success lift.

```bash
PYTHONPATH=src python tests/experience_pool_selftest.py
```

