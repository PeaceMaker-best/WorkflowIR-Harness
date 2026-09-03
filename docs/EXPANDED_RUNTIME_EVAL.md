# Expanded runtime evaluation

This report extends the frozen five-workflow Developer study without rerunning trials that had already passed. It is a post-hoc custom engineering evaluation over pre-generated Chat2Workflow artifacts, not an official leaderboard submission or an end-to-end natural-language generation experiment.

> **Legacy/pre-P0 snapshot:** these reported numbers predate the deterministic structural validator and the rule that treats every outcome containing an unverified file-valued field—including mixed file-and-text outputs—as unverified. The current code has not yet rerun the complete matrix under that protocol. This document records historical evidence, not a claim that the current revision reproduces the table.

## Protocol

- Runtime: one Dify 1.9.2 deployment.
- Model: `doubao-seed-evolving`, thinking disabled.
- Inputs: three fixed functional inputs per workflow.
- Artifact source: one frozen, pre-generated YAML workflow per arm and task; this repository does not regenerate Workflow IR or Dify YAML in this evaluation.
- Shared runtime compatibility: both arms receive the same environment-only Dify compatibility handling. Requirement-aware changes apply only to the staged artifact bundle and are not evaluated as an isolated component.
- Experience pool: disabled, so this measures the deterministic harness and adapter only.
- Incremental execution: previously successful `(arm, workflow, input)` trials are reused; only missing or failed trials are scheduled.
- Concurrency: independent workflows ran concurrently. The final isolated timeout probe ran three inputs concurrently because no runtime memory was enabled.
- Runtime acceptance: Dify execution succeeds and every required output is non-empty.
- Semantic success in this historical snapshot used the official Resolve-stage prompt with a same-model, temperature-zero judge. Outputs were truncated to 16,000 characters, there was no independent human adjudication, and some outputs containing unchecked file fields were marked semantic-pass. The new P0 evaluator marks every outcome containing an unverified file-valued field—including mixed file-and-text outputs—as unverified; the table has not yet been recomputed under that rule.
- Structural validation: the deterministic validator checks graph endpoints, edge structure, and reference structure. Passing it does not guarantee correct variable field names, output types, file contents, or business semantics.

The staged arm has 19 workflows. Official comparison artifacts exist for 16 of them, so comparative claims use only those paired workflows.

## Paired result: 16 tasks, 48 logical trials per arm

The paired matrix contains 16 tasks × 3 fixed inputs × 2 systems = 96 system-side logical trials, or 48 matched input pairs. Incremental runs may reuse previously passing records, so this count describes the comparison matrix rather than the number of freshly executed requests in every rerun.

| Arm | Execution pass | Runtime acceptance | Stable runtime workflows | Semantic pass | Stable semantic workflows |
|---|---:|---:|---:|---:|---:|
| Official agentic artifacts | 35/48 | 32/48 (66.7%) | 10/16 | 23/48 (47.9%) | 5/16 |
| WorkflowIR-Harness | 45/48 | 45/48 (93.8%) | 15/16 | 34/48 (70.8%) | 9/16 |

On the paired set, the complete staged artifact bundle records Dify execution success of 45/48 (93.8%) versus 35/48 (72.9%) for the official-artifact arm, a 20.9-point difference. Runtime acceptance, which additionally requires non-empty required outputs, is 45/48 (93.8%) versus 32/48 (66.7%), a 27.1-point difference. Semantic-Judge pass rate differs by 22.9 points, subject to the proxy limitations above. Because no component ablation was run, none of these differences can be attributed independently to the IR prototype, requirement patching, compatibility adapter, or bounded repair.

## Selected token evidence

The reported 29.8% generation-token reduction is limited to the selected `Mermaid_2` case (35,457 vs. 24,877 generation tokens). It is not an average over the 16 paired tasks, excludes model use during Dify workflow execution, and is not reproduced by the runtime CLI in this repository.

## Harness coverage: 19 workflows, 57 trials

| Metric | Result |
|---|---:|
| Dify execution pass | 54/57 (94.7%) |
| Runtime acceptance | 54/57 (94.7%) |
| Stable runtime workflows | 18/19 |
| Semantic pass | 40/57 (70.2%) |
| Stable semantic workflows | 11/19 |

The three runtime failures are all `StudyPlanner_3` timeouts at the 240-second client boundary. They are retained as failures; they are not replaced or reclassified as generation successes.

## Changes included in the staged artifact bundle

The following items document changes present in the evaluated staged bundle. They are descriptive case histories, not controlled ablations, and do not establish their individual contribution to the aggregate result.

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

This evidence supports only a scoped bundle-level claim: under the disclosed custom protocol and shared runtime-compatibility handling, the complete staged artifacts recorded higher executability than the paired official artifacts. The repository contains a Workflow IR validation prototype, but not a runnable natural-language-to-IR-to-Dify generator CLI. The experience pool was disabled and contributes none of the reported result. No component ablation was run, so the result must not be attributed to any individual contract, adapter, validator, or repair mechanism. The study does not establish a new official Chat2Workflow state of the art. A publication-grade comparison would additionally implement and freeze the generation path, publish all generated YAML, repeat generation across seeds, use held-out tasks, and add independent human review.
