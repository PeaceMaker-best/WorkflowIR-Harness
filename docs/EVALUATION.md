# Scoped engineering evaluation

## Dataset origin

The workflow requirements and official Agentic comparison artifacts originate from the public Chat2Workflow benchmark. Github-dependent cases were excluded from the primary runtime study because their external credential and service state could not be frozen with the rest of the environment.

The expanded study contains:

- 19 WorkflowIR-Harness workflows;
- 16 workflows with paired official Agentic artifacts;
- three fixed functional inputs per workflow;
- 48 paired executions and 57 total harness executions.

## Why this is not the official benchmark protocol

The project evaluates an engineering harness, not only a model response. It therefore permits feedback that a production workflow platform naturally exposes:

- import and publish errors;
- node-level execution traces;
- variable and output-contract violations;
- infrastructure failures and timeouts.

This feedback can trigger a bounded repair followed by a full workflow rerun. The generator and repair controller never receive the reference workflow, expected judge answer, or a hidden test solution.

Because this protocol changes the information and repair boundary, the results are not presented as an official Chat2Workflow leaderboard submission.

## Primary metric: stable workflow

A workflow is stable only if one frozen configuration passes all three assigned functional inputs. This prevents three independently lucky generations from being counted as one reliable workflow.

Configuration-level and input-level results are reported together:

1. stable runtime workflows;
2. runtime acceptance;
3. stable semantic workflows;
4. semantic task success;
5. output-contract pass rate;
6. repair yield;
7. infrastructure failure rate.

## Paired result

| Method | Stable runtime workflows | Runtime acceptance | Stable semantic workflows | Semantic success |
|---|---:|---:|---:|---:|
| Official Agentic artifacts | 10/16 | 32/48 (66.7%) | 5/16 | 23/48 (47.9%) |
| WorkflowIR-Harness | **15/16** | **45/48 (93.8%)** | **9/16** | **34/48 (70.8%)** |

## Full harness result

Across all 19 harness workflows:

- runtime acceptance: 54/57 (94.7%);
- stable runtime workflows: 18/19;
- the three retained failures were **StudyPlanner_3** timeouts.

## Token accounting

Generation tokens, workflow-runtime tokens, and semantic-judge tokens are separate ledgers. Only generation tokens are used to compare builder context cost. Runtime tokens depend on the task payload, and judge tokens are experiment overhead rather than product generation cost.

The repository currently reports exact generation tokens for the selected Mermaid case. An aggregate paired generation-token study is future work.

## No repeated-sampling success metric

The main runtime tables use frozen workflows. A failed workflow is not replaced by a different lucky sample. Infrastructure-only retries are disclosed separately; typed task repairs must retain the original issue, repair action, and full-rerun result.
