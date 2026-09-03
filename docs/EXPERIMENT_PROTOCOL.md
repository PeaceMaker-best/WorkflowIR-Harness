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
4. **Semantic task status (TSR proxy)**: the benchmark Resolve-stage prompt and same-model, temperature-zero Judge accept an output containing no unverified file-valued fields. Every result containing an unverified file field—including mixed file-and-text output—is marked `unverified` until an independent file-content check exists. Judged text is capped at 16,000 characters and no independent human adjudication has been performed.
5. **Deterministic structural validation**: checks graph endpoints, edge structure, and reference structure. A pass does not guarantee correct variable field names, output types, file contents, or business semantics.
6. **Stable workflow pass rate**: a workflow counts only when all three official inputs pass semantic evaluation.
7. **Repair yield**: failed executions recovered by a bounded, error-class-specific retry. Report the numerator and denominator, not only a percentage.
8. **Infrastructure failure rate**: provider/runtime/database failures are recorded separately and never treated as generation errors.
9. **Degraded artifact rate**: compatibility descriptors are counted separately from native downloadable files.

Report configuration-level and input-level results together. Do not use exact YAML/JSON equality as the primary metric because harmless IDs, layout positions, and field order can differ.

## Reporting rule

Publish two tables:

- **Raw same-run result**: no result replacement.
- **Infrastructure-retried result**: only an explicitly identified infrastructure failure may be rerun on the same frozen input; the replacement key and original error class must be recorded.

The infrastructure-retried table is an engineering availability result. The raw table remains the primary reproducibility result.

## Expanded paired accounting

The expanded paired comparison contains 16 tasks × 3 fixed inputs × 2 systems = 96 system-side logical trials, or 48 matched input pairs. Each arm uses one frozen, pre-generated workflow per task. Dify execution success and runtime acceptance are reported separately: execution improves from 35/48 (72.9%) to 45/48 (93.8%), while execution plus required non-empty outputs improves from 32/48 (66.7%) to 45/48 (93.8%).

Generation-token evidence is available only for the selected `Mermaid_2` case and must not be reported as a 16-task average.

## Experimental repair-memory follow-up

The frozen comparison above remains unchanged. A future v0.2 run must publish
three phases separately: cold without a database, candidate shadow mode, and warm
mode with promoted policies. It must additionally report promotion precision,
quarantine count, repair attempts per successful workflow, and model repair calls
avoided. Reusing the same trials to both promote a policy and report warm uplift
must be disclosed; a held-out later input is preferred.

The current three-input sequence cannot by itself demonstrate default-threshold Warm uplift: a new candidate reaches three successes only after the third matching input, leaving no fourth held-out input to consume it. No self-evolution or online-improvement claim is made from the existing lifecycle regression.
