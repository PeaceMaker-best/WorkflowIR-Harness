# Scoped evaluation protocol

This evaluation is intentionally limited to five Developer workflows: `Code_1`, `Code_2`, `Code_3`, `Mermaid_1`, and `Mermaid_2`. It is a post-hoc developer-set regression, not a blind test and not a claim about the full benchmark leaderboard.

## Frozen comparison

- Baseline: official Agentic-generated workflow.
- Harness arm: staged workflow plus requirement contracts, runtime contracts, validation, and bounded directed repair.
- Runtime: the same Dify 1.9.2 deployment.
- Model: the same `doubao-seed-evolving` endpoint with thinking disabled.
- Inputs: three distinct official functional inputs per workflow.
- Total: 15 execution trials per arm.
- Shared compatibility adapter: both arms receive environment-only Dify compatibility fixes. Requirement-aware repairs apply only to the harness arm.
- History/experience pool: disabled in this first comparison.

## Metrics

1. **Import/publish success**: the workflow is accepted and published by Dify.
2. **Execution success rate (ESR)**: the Dify run completes without a workflow or node error.
3. **Output-contract pass rate (OCPR)**: required outputs exist and have the expected runtime shape.
4. **Semantic task success rate (TSR)**: the benchmark resolve-stage judge accepts the functional result.
5. **Stable workflow pass rate**: a workflow counts only when all three official inputs pass semantic evaluation.
6. **Repair yield**: failed executions recovered by a bounded, error-class-specific retry. Report the numerator and denominator, not only a percentage.
7. **Infrastructure failure rate**: provider/runtime/database failures are recorded separately and never treated as generation errors.
8. **Degraded artifact rate**: compatibility descriptors are counted separately from native downloadable files.

Report configuration-level and input-level results together. Do not use exact YAML/JSON equality as the primary metric because harmless IDs, layout positions, and field order can differ.

## Reporting rule

Publish two tables:

- **Raw same-run result**: no result replacement.
- **Infrastructure-retried result**: only an explicitly identified infrastructure failure may be rerun on the same frozen input; the replacement key and original error class must be recorded.

The infrastructure-retried table is an engineering availability result. The raw table remains the primary reproducibility result.
