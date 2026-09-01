# Scoped Developer Evaluation

> This is a frozen five-workflow developer subset, not a blind test and not a full leaderboard result.

## Protocol

- Cases: `Code_1`, `Code_2`, `Code_3`, `Mermaid_1`, `Mermaid_2`.
- Three official functional inputs per workflow: 15 execution trials per arm.
- Same Dify runtime and model; thinking disabled.
- Semantic task success follows the benchmark resolve-stage judge; infrastructure failures are reported separately.
- A workflow is stable only when all three inputs pass semantic evaluation.
- Markdown artifact descriptors are marked degraded and are not claimed as native downloadable files.

## Results

| Arm | Import/publish | Execution | Output contract | Semantic task | Stable workflows | Infra failures | Degraded artifacts |
|---|---:|---:|---:|---:|---:|---:|---:|
| official | 15/15 (100.0%) | 12/15 (80.0%) | 9/15 (60.0%) | 8/15 (53.3%) | 2/5 (40.0%) | 0 | 3 |
| ours | 15/15 (100.0%) | 15/15 (100.0%) | 15/15 (100.0%) | 15/15 (100.0%) | 5/5 (100.0%) | 0 | 3 |

## Per-case semantic results

| Case | official | ours |
|---|---:|---:|
| Code_1 | 2/3 (66.7%) | 3/3 (100.0%) |
| Code_2 | 0/3 (0.0%) | 3/3 (100.0%) |
| Code_3 | 3/3 (100.0%) | 3/3 (100.0%) |
| Mermaid_1 | 3/3 (100.0%) | 3/3 (100.0%) |
| Mermaid_2 | 0/3 (0.0%) | 3/3 (100.0%) |

## Infrastructure retry audit

Exactly 1 failed trial was replaced after confirming an infrastructure-only failure and rerunning the same input.
- `ours/Mermaid_2/test3`

## Interpretation

The numbers are suitable for regression and engineering validation on this scoped subset. They must not be presented as a full-benchmark or blind-test ranking.
