# Experimental Lifecycle for Runtime Repair Policies

## Scope

This module implements an experimental candidate/active/quarantined lifecycle for
generic repair-policy text. It is not autonomous model training, prompt rewriting,
source-code mutation, or a demonstrated self-evolving Agent. The stored unit is a
generic policy associated with an exact task scope, failure class, node type,
normalized error signature, and graph node-type signature; it is not the successful
repair Diff, code, control flow, or full Trace.

The current failure trace always remains authoritative.

## Lifecycle

```text
verified whole-graph repair
          |
          v
      candidate  -- repeated verified success -->  active
          |                                      /      |
          | two consecutive failures            |      | two consecutive failures
          v                                      |      v
      quarantined <------------------------------+  quarantined
          |
          +-- later independent success --> new candidate version
```

States have deliberately different execution rights:

- `candidate`: stored for shadow accounting but never injected into a repair.
- `active`: eligible for same-task retrieval and prompt injection.
- `quarantined`: excluded from retrieval and retained for audit and lineage.

## Promotion gate

The default promotion gate requires:

1. three complete workflow successes for the same policy fingerprint;
2. a Wilson lower-bound reliability of at least `0.40`;
3. no unresolved consecutive-failure quarantine condition.

A success is counted only after the repaired workflow passes Dify execution and
required-output checks. Import success, node success, or model confidence alone
cannot promote a policy, but this gate does not include the separate semantic Judge.

When no active policy was used, a successful trace-guided repair contributes one
candidate success. When an active policy was used, the same trial updates that
policy once. This prevents double counting.

## Retrieval gate

Online retrieval admits only `active` policies satisfying all of:

- exact task scope;
- exact failure class;
- compatible node type;
- error-token Jaccard threshold;
- graph node-type Jaccard threshold;
- retention TTL.
Online execution selects only the top-ranked eligible policy so each outcome has an attributable success or failure update.


Candidates can be requested with `include_candidates=True` only for diagnostics
and offline shadow evaluation.

## Regression control and rollback

An active policy is automatically quarantined after two consecutive task-level
failures. Infrastructure failures, provider throttling, and transient plugin
capacity errors do not update policy quality.

If an independently repaired workflow later produces the same policy
fingerprint, the quarantined record stays immutable and a new candidate version
is created with `parent_id` pointing to it. This gives the system an explicit
rollback and recovery lineage instead of silently overwriting history.

## Audit model

The experience table stores:

- policy version and lifecycle state;
- success, failure, and consecutive-failure counters;
- parent version;
- promotion and quarantine timestamps;
- the last normalized reason.

The event table stores candidate creation, promotion, and quarantine transitions.
Neither table stores raw user input, answer text, full traces, credentials, URLs,
emails, or platform parameters.

## Concurrency

Inputs within the same `(arm, task)` group execute sequentially and different tasks
may run concurrently as threads in one runner process. SQLite WAL mode and a
process-local `threading.RLock` serialize that path. There is no inter-process
lock, so separate processes must not share one experience database.

## Configuration

```bash
PYTHONPATH=src python src/run_dify_all3.py \
  --arm staged \
  --result-dir results/evolving \
  --experience-db results/evolving.sqlite3 \
  --experience-promotion-successes 3 \
  --experience-promotion-reliability 0.40 \
  --experience-quarantine-failures 2
```

## Validation

```bash
PYTHONPATH=src python tests/self_evolving_pool_selftest.py
```

The deterministic regression verifies:

- candidate shadow-only behavior;
- threshold-based promotion;
- active-policy retrieval;
- consecutive-failure quarantine;
- versioned recovery lineage;
- migration from a v0.1 database;
- secret and raw-output exclusion.

## Evaluation metrics for an online run

A credible self-evolution experiment should report these separately:

- cold task success: no experience database;
- candidate phase success: database enabled, candidates not injected;
- warm task success: promoted policies eligible;
- promotion precision: promoted policies that remain successful;
- quarantine rate and rollback count;
- repair attempts per successful workflow;
- number of model repair calls avoided.

The current repository validates lifecycle mechanics offline. A candidate is not
injected before promotion, so its three promotion successes do not causally validate
the candidate hint itself. With three default inputs and a three-success threshold,
promotion occurs only after the last matching input; a later held-out input is
required for a credible Warm comparison. No online success-rate or self-evolution
improvement is currently claimed.
