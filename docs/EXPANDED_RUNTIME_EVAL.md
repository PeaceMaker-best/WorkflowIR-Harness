# Expanded runtime evaluation

This report extends the frozen five-workflow Developer study without rerunning trials that had already passed. It is a custom engineering evaluation over Chat2Workflow artifacts, not an official leaderboard submission.

## Protocol

- Runtime: one Dify 1.9.2 deployment.
- Model: `doubao-seed-evolving`, thinking disabled.
- Inputs: three fixed functional inputs per workflow.
- Experience pool: disabled, so this measures the deterministic harness and adapter only.
- Incremental execution: previously successful `(arm, workflow, input)` trials are reused; only missing or failed trials are scheduled.
- Concurrency: independent workflows ran concurrently. The final isolated timeout probe ran three inputs concurrently because no runtime memory was enabled.
- Runtime acceptance: Dify execution succeeds and every required output is non-empty.
- Semantic success: the official Resolve-stage prompt is used with a same-model, temperature-zero judge. This remains a low-cost proxy, not human adjudication.

The staged arm has 19 workflows. Official comparison artifacts exist for 16 of them, so comparative claims use only those paired workflows.

## Paired result: 16 workflows, 48 trials per arm

| Arm | Execution pass | Runtime acceptance | Stable runtime workflows | Semantic pass | Stable semantic workflows |
|---|---:|---:|---:|---:|---:|
| Official agentic artifacts | 35/48 | 32/48 (66.7%) | 10/16 | 23/48 (47.9%) | 5/16 |
| WorkflowIR-Harness | 45/48 | 45/48 (93.8%) | 15/16 | 34/48 (70.8%) | 9/16 |

On the paired set, runtime acceptance improves by 27.1 percentage points and semantic success improves by 22.9 percentage points.

## Harness coverage: 19 workflows, 57 trials

| Metric | Result |
|---|---:|
| Dify execution pass | 54/57 (94.7%) |
| Runtime acceptance | 54/57 (94.7%) |
| Stable runtime workflows | 18/19 |
| Semantic pass | 40/57 (70.2%) |
| Stable semantic workflows | 11/19 |

The three runtime failures are all `StudyPlanner_3` timeouts at the 240-second client boundary. They are retained as failures; they are not replaced or reclassified as generation successes.

## Failure-driven adapter upgrades

### ECharts parameter contract

The generated graph passed arrays directly to the installed ECharts tool, while the compatible plugin version accepts semicolon-delimited numeric and label strings. The adapter now inserts deterministic array-to-delimited-text nodes and rewrites only the affected tool selectors. `PerformanceChart_4` moved from 0/3 to 3/3 runtime acceptance.

### Multi-file upload contract

The runner previously handled one file descriptor but not a list of local files. It now uploads every item independently and passes Dify-compatible `file-list` descriptors. `ResumeScreening_3` moved from empty outputs to 3/3 runtime acceptance.

### Iteration budget guard

The adapter detects typed array inputs to an Iteration node, inserts a deterministic fan-out cap, and records the repair in adapter actions. The default cap is 12 items; the isolated `StudyPlanner_3` probe exported `HARNESS_MAX_ITERATION_ITEMS=4`. The workflow still exceeded 240 seconds, so it remains the explicit latency boundary of this run.

## Incremental and parallel runner

`--resume-from` loads an existing `result.json`, reuses only trials whose runtime acceptance is true, and schedules failed or missing keys. `--sample-parallel` parallelizes individual fixed inputs when the experience pool is disabled.

```bash
PYTHONPATH=src python src/run_dify_all3.py \
  --arm staged \
  --workers 12 \
  --sample-parallel \
  --resume-from results/previous/result.json \
  --result-dir results/incremental
```

Sample-level parallelism is rejected when `--experience-db` is enabled. Warm repair memory requires the three inputs of a task to remain sequential so that promotion and feedback order are auditable.

## Published evidence

- `expanded_metrics.json` contains the aggregate runtime and semantic summaries.
- `expanded_trials.json` contains one compact, secret-free record per arm, workflow, and fixed input.

## Claim boundary

This evidence supports a scoped claim: deterministic requirement contracts, platform adapters, and bounded runtime validation materially improve executability on the tested artifacts. It does not establish a new official Chat2Workflow state of the art, and it does not isolate every component's causal contribution. A publication-grade comparison would additionally freeze generation prompts, publish all generated YAML, repeat generation across seeds, and use independent human review.
