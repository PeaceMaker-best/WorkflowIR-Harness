# WorkflowIR-Harness: Contract-Guided Generation, Validation, and Runtime Repair

This package turns generated workflow configurations into an auditable execution experiment instead of judging them by JSON equality.

## Abstract

WorkflowIR-Harness converts natural-language workflow generation from a JSON imitation task into an executable, auditable pipeline. It separates requirement semantics, graph structure, parameter binding, platform adaptation, and runtime repair, then evaluates whether a generated workflow can actually complete fixed functional inputs on Dify.

## Contributions

- Requirement-contract repair and deterministic graph validation before platform import.
- A Dify adapter that keeps platform compatibility changes separate from workflow semantics.
- Trace-guided node repair with at most two retries; topology failures remain full-regeneration events.
- A task-isolated runtime experience pool that stores only normalized failure signatures and verified repair policies.

## Frozen developer result

| Arm | Execution | Output contract | Semantic task | Stable workflows |
|---|---:|---:|---:|---:|
| Official agentic artifacts | 12/15 | 9/15 | 8/15 (53.3%) | 2/5 |
| WorkflowIR-Harness | 14/15 | 14/15 | 14/15 (93.3%) | 4/5 |

The scoped evaluation contains five Developer workflows and three fixed inputs per workflow. The single remaining harness failure was an audited Dify plugin-database capacity error; an exact infrastructure-only retry passed. This is a developer subset result, not a blind or full leaderboard claim.


## Pipeline

`Requirement contract -> shared Dify compatibility adapter -> import/publish -> execute -> output-contract check -> semantic judge -> typed repair -> full rerun`

The core design separates:

- requirement semantics from platform configuration;
- graph, binding, execution, and infrastructure failures;
- task repair retries from infrastructure retries;
- native output artifacts from degraded compatibility descriptors.

## Reproduce the frozen five-case report

```bash
PYTHONPATH=src python src/make_scoped_report.py \
  --result /path/to/raw/result.json \
  --semantic /path/to/raw/semantic.json \
  --output-dir /path/to/report_raw
```

For an audited infrastructure retry, also pass `--replacement-result` and `--replacement-semantic`. The script only replaces a base trial when its error matches a known infrastructure marker and the same arm/case/input succeeds semantically in the replacement run.

See:

- `docs/EXPERIMENT_PROTOCOL.md` for metric definitions.
- `docs/BAD_CASES_AND_REPAIRS.md` for failure-driven upgrades.
- `docs/SCOPED_DEVELOPER_EVAL_RAW.md` for the primary result.
- `docs/SCOPED_DEVELOPER_EVAL_INFRA_RETRIED.md` for the availability-adjusted result.

## Claim boundary

The current evidence covers five Developer workflows and fifteen functional executions per arm. It supports a scoped engineering claim, not a full Chat2Workflow leaderboard claim.

## Runtime experience pool

The pool is a repair memory, not an answer cache. A policy is written only after a failed node is repaired and the complete workflow passes again.

Stored fields:

- exact task scope and failure class;
- failing node type and graph node-type signature;
- normalized, redacted error tokens;
- generic repair policy plus success/failure counters and timestamps.

Retrieval gates:

- exact task scope;
- exact failure class;
- compatible node type;
- minimum error-token and graph-signature similarity;
- 90-day TTL and per-task retention cap.

Raw user input, model output, answer text, API keys, URLs, emails, and full traces are never stored. Inputs for one task run sequentially so earlier verified repairs can warm later inputs, while different tasks still run in parallel.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python tests/experience_pool_selftest.py
```

To run the frozen three-input execution harness, point it at a Dify installation and a Chat2Workflow-compatible check file:

```bash
export DIFY_ADMIN_FILE=/secure/path/dify_admin.env
export BENCH_CHECK_FILE=/path/to/check_pass_stage.json
export BENCH_CASE_FILES=/path/to/case_files
PYTHONPATH=src python src/run_dify_all3.py --arm staged --workers 5 --experience-db results/repair_memory.sqlite --result-dir results/run
```

`--experience-db` is optional. Without it, the runner performs trace-guided repair but does not persist repair experience.

## Reproducibility

- [Experiment protocol](docs/EXPERIMENT_PROTOCOL.md)
- [Raw frozen result](docs/SCOPED_DEVELOPER_EVAL_RAW.md)
- [Infrastructure-retried result](docs/SCOPED_DEVELOPER_EVAL_INFRA_RETRIED.md)
- [Bad cases and repair decisions](docs/BAD_CASES_AND_REPAIRS.md)
- [Runtime experience pool](docs/RUNTIME_EXPERIENCE_POOL.md)

## Acknowledgement

The example tasks, node catalog fixture, and official comparison artifacts originate from [Chat2Workflow](https://github.com/zjunlp/Chat2Workflow): *A Benchmark for Generating Executable Visual Workflows with Natural Language*. WorkflowIR-Harness is an independent engineering extension and does not claim affiliation with the benchmark authors.

## License

MIT. Upstream benchmark assets retain their original notice in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

