# WorkflowIR-Harness

[中文](README.md) · [English](README_EN.md)

![WorkflowIR-Harness: less context, more stable workflows](assets/hero-opencode-vs-workflowir.svg)

**Executable evidence for pre-generated workflows.**

The current runnable project is a deterministic execution and assurance harness for pre-generated Dify workflow artifacts. It applies shared runtime compatibility handling, imports and publishes frozen YAML, executes fixed inputs, checks required outputs, records traces, and performs bounded runtime repair. The repository also contains a provider-independent Workflow IR/pipeline prototype, but it does not yet expose a reproducible natural-language-to-IR-to-Dify CLI.

## Executable Dify evidence

[![Code_3 actual Dify UI: workflow canvas, logs, result, and node tracing](examples/code3-demo/screenshots/code3-native-dify-flow.png)](examples/code3-demo/README.md)

The [Code_3 executable demo](examples/code3-demo/README.md) follows one frozen 14-node, 16-edge workflow through the actual Dify Canvas, Workflow Logs, Result panel, and per-node Tracing view. The captured application is published, its selected run is marked SUCCESS, and the same frozen artifact passed all three fixed inputs.

## Selected case: 29.8% fewer generation tokens

On the same two-round **Mermaid_2** task, with the same model and thinking disabled:

| Method | Generation tokens | Model calls | Dify execution | Semantic success |
|---|---:|---:|---:|---:|
| OpenCode Agentic | 35,457 | 2 | 3/3 | 0/3 |
| WorkflowIR-Harness | **24,877** | 5 | 3/3 | **3/3** |

In this selected log, the harness path recorded **29.8% fewer generation tokens despite making more model calls**. Its artifact also separated the knowledge summary from Mermaid source through an explicit output contract, while the OpenCode artifact mixed them in one value.

> This evidence is limited to the selected `Mermaid_2` case. It is not an aggregate token claim, does not isolate the cause of the difference, and is not an official leaderboard result. The runtime CLI in this repository does not reproduce the upstream generation calls. See the [full trace and accounting](docs/CASE_STUDY_MERMAID2.md).

## Why an execution harness?

Pre-generated workflow artifacts still fail at several observable boundaries:

- Dify import and publish compatibility;
- node execution and provider availability;
- required output names and non-empty values;
- task-level semantic proxy checks;
- auditable, bounded retries after runtime-visible failures.

WorkflowIR-Harness evaluates those boundaries directly. It does not establish that a specialized generator replaces coding agents, because the published comparison starts from frozen, already generated workflow artifacts.

![Contract-guided staged generation pipeline](assets/pipeline-pixel.svg)

## Current runnable path

```text
Frozen pre-generated YAML
        ↓
Requirement/runtime contract patch
        ↓
Shared Dify compatibility handling
        ↓
Import/publish → execute fixed input → required-output check
        ↓
Trace-guided bounded repair → complete workflow rerun
```

Both comparison arms receive the same environment-only Dify compatibility handling. Requirement-aware changes are applied only to the staged artifact bundle. The real runner records import, execution, output-contract, and infrastructure failures. Detailed Graph and Binding issue classes exist primarily in the separate Workflow IR/validator prototype; the main runtime study does not claim one unified four-layer classifier.

## Workflow IR pipeline prototype

The provider-independent prototype defines injectable Rewrite, Retrieve, Graph, Bind, Validate, and Repair interfaces plus Direct, Staged, Guarded, and Adaptive profiles. Its deterministic structural validator checks graph endpoints, edge structure, and reference structure; it does not yet guarantee correct variable field names, output types, file contents, or business semantics. The self-test uses in-memory stub functions, so this remains architecture scaffolding rather than a production generator or a runnable natural-language-to-Dify path.

![Direct, staged, guarded, and adaptive assurance profiles](assets/assurance-profiles.svg)

| Profile | Intended use | Enabled path |
|---|---|---|
| **direct** | Prototype API | Injected direct callable |
| **staged** | Prototype API | Injected Rewrite → Retrieve → Graph → Bind callables |
| **guarded** | Prototype API | Staged path + injected validation/repair |
| **adaptive** | Prototype API | Guarded path with an experience-use flag |

The repository does not report production effectiveness for these profiles, and automatic profile selection remains future work.

## 16 tasks, 48 matched inputs, 96 logical system-side trials

A workflow is **stable** only when the same frozen configuration passes all three fixed functional inputs. This is the primary engineering signal: one successful sample is not enough.

> **Legacy result boundary:** the table below is a pre-P0 snapshot produced before the deterministic structural validator and the rule that marks every outcome containing an unverified file-valued field—including mixed file-and-text outputs—as unverified. The current code has not yet completed a full rerun under the new protocol, so these numbers must not be presented as reproduced by the current version.

![Scoped evaluation: stable workflows and task success](assets/scoped-evaluation.svg)

The paired matrix contains **16 public Chat2Workflow tasks × 3 fixed inputs × 2 systems = 96 logical system-side trials**, organized as **48 matched pairs**. Incremental reruns may reuse already passing records, so 96 describes the comparison matrix rather than the number of newly executed requests in every report. Task-level stability still requires one frozen workflow to pass all three inputs:

| Method | Dify execution | Runtime acceptance | Stable runtime workflows | Semantic-Judge pass | Stable semantic workflows |
|---|---:|---:|---:|---:|---:|
| Official Agentic artifacts | 35/48 (72.9%) | 32/48 (66.7%) | 10/16 | 23/48 (47.9%) | 5/16 |
| Staged artifact bundle | **45/48 (93.8%)** | **45/48 (93.8%)** | **15/16** | **34/48 (70.8%)** | **9/16** |

Both arms receive the same environment-only runtime compatibility handling. No component ablation was run, so the bundle-level differences cannot be attributed independently to Workflow IR, requirement patching, the adapter, validation, or bounded repair.

Across all 19 staged workflows, 18/19 passed all three runtime inputs; 54/57 logical trial records passed runtime acceptance (94.7%). The remaining three records were retained as **StudyPlanner_3** timeouts.

The tasks originate from the public [Chat2Workflow](https://github.com/zjunlp/Chat2Workflow) benchmark, but this project intentionally uses a different post-hoc engineering protocol over frozen artifacts. Runtime-visible import errors, node traces, and output-contract violations may guide bounded repair. Reference workflows and Judge answers are not exposed to repair. The semantic result is still a low-cost proxy: the same model is used at temperature zero, outputs are capped at 16,000 characters, and there is no independent human adjudication. The legacy snapshot accepted outputs whose file contents were not inspected; the new P0 evaluator marks every outcome containing an unverified file-valued field—including mixed file-and-text outputs—as unverified until an independent content check exists. See [Evaluation protocol](docs/EVALUATION.md) and [Claims and limitations](docs/CLAIMS_AND_LIMITATIONS.md).

## Failure is evidence, not another lottery ticket

The engineering loop is:

~~~text
frozen YAML → runtime patch/adapter → execute → classify → bounded repair → complete workflow rerun
~~~

It does not repeatedly sample new workflows until one happens to pass. A failed runtime attempt retains an auditable next action. The optional repair-memory prototype stores generic text policies rather than successful code Diffs or executable Skills; it was disabled in the reported comparison, has no held-out Warm-uplift evidence, and is not claimed as self-evolution.

## Package layout

~~~text
src/workflowir_harness/
├── domain.py       # requirement, workflow, issue, and outcome types
├── profiles.py     # direct / staged / guarded / adaptive modes
├── telemetry.py    # call-level and success-normalized token accounting
└── pipeline.py     # provider-independent staged orchestration

src/                # existing Dify adapter, validators, runner, and repair memory
tests/              # offline, runtime-policy, and pipeline self-tests
docs/               # method, case study, evaluation, and claim boundaries
~~~

The new package is intentionally thin and provider-independent. Existing experiment scripts remain available while they are migrated behind stable interfaces.

## Quick start

~~~bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

PYTHONPATH=src python tests/pipeline_selftest.py
PYTHONPATH=src python tests/offline_selftest.py
PYTHONPATH=src python tests/experience_pool_selftest.py
~~~

To run the Dify execution harness, provide a private admin environment file and the upstream evaluation assets:

~~~bash
export DIFY_ADMIN_FILE=/secure/path/dify_admin.env
export BENCH_CHECK_FILE=/path/to/check_pass_stage.json
export BENCH_CASE_FILES=/path/to/case_files

PYTHONPATH=src python src/run_dify_all3.py \
  --arm staged \
  --workers 5 \
  --result-dir results/run
~~~

Secrets, raw traces, user content, and local absolute paths are excluded from the repository.

## Reproducibility

- [Mermaid_2 case study](docs/CASE_STUDY_MERMAID2.md)
- [Scoped evaluation protocol](docs/EVALUATION.md)
- [Claims and limitations](docs/CLAIMS_AND_LIMITATIONS.md)
- [Expanded runtime evaluation](docs/EXPANDED_RUNTIME_EVAL.md)
- [Bad cases and repair decisions](docs/BAD_CASES_AND_REPAIRS.md)
- [Runtime experience pool](docs/RUNTIME_EXPERIENCE_POOL.md)
- [Compact trial ledger](docs/expanded_trials.json)

## Acknowledgement

The public tasks, node-catalog fixture, and official comparison artifacts originate from [Chat2Workflow](https://github.com/zjunlp/Chat2Workflow), *A Benchmark for Generating Executable Visual Workflows with Natural Language*. WorkflowIR-Harness is an independent engineering extension and is not affiliated with the benchmark authors.

## License

MIT. Upstream assets retain their original notices in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
