# Experimental task-scoped repair memory

The pool is an experimental store for generic repair-policy hints. It is designed to study repeated repair cost without becoming an answer cache, but the current repository does not demonstrate online task-success or cost improvement from it.
The runner wraps these base storage and retrieval mechanics with the candidate, active, and quarantined lifecycle documented in [SELF_EVOLUTION.md](SELF_EVOLUTION.md). Only promoted active policies are eligible for injection.


## Lifecycle

1. Execute a validated workflow.
2. Detect a node-level runtime error from the trace or output error envelope.
3. Classify the failure and identify the failing node type.
4. Retrieve the top promoted policy under strict same-task gates for attributable feedback.
5. Inject the current trace as authoritative evidence and past policies as optional hints.
6. Rerun the complete graph; never accept a local repair without full-graph validation.
7. Persist a generic text policy only when the rerun passes Dify execution and required-output checks. This is not semantic validation and does not store the successful code Diff, control flow, or full Trace.

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

Fixed inputs within one task scope execute sequentially and different tasks may run concurrently as threads inside one runner process. The implementation uses a process-local `threading.RLock` plus SQLite WAL/busy timeout; it does not provide an inter-process lock. Multiple runner processes must not share one experience database.

## Validation

The offline regression verifies storage/retrieval mechanics, task isolation, wrong-class and wrong-graph rejection, redaction, same-process threaded writes, and the absence of secret or raw-output columns. Its “warm hit” is a synthetic retrieval check, not a held-out end-to-end task result. With the default three-success promotion threshold, the three-input protocol promotes a new candidate only after its final input, so a separate later or held-out input is required to measure Warm benefit.

```bash
PYTHONPATH=src python tests/experience_pool_selftest.py
```

