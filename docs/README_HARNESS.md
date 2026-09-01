# Workflow execution harness

This package turns generated workflow configurations into an auditable execution experiment instead of judging them by JSON equality.

## Pipeline

`Requirement contract -> shared Dify compatibility adapter -> import/publish -> execute -> output-contract check -> semantic judge -> typed repair -> full rerun`

The core design separates:

- requirement semantics from platform configuration;
- graph, binding, execution, and infrastructure failures;
- task repair retries from infrastructure retries;
- native output artifacts from degraded compatibility descriptors.

## Reproduce the frozen five-case report

```bash
python make_scoped_report.py \
  --result /path/to/raw/result.json \
  --semantic /path/to/raw/semantic.json \
  --output-dir /path/to/report_raw
```

For an audited infrastructure retry, also pass `--replacement-result` and `--replacement-semantic`. The script only replaces a base trial when its error matches a known infrastructure marker and the same arm/case/input succeeds semantically in the replacement run.

See:

- `EXPERIMENT_PROTOCOL.md` for metric definitions.
- `BAD_CASES_AND_REPAIRS.md` for failure-driven upgrades.
- `SCOPED_DEVELOPER_EVAL_RAW.md` for the primary result.
- `SCOPED_DEVELOPER_EVAL_INFRA_RETRIED.md` for the availability-adjusted result.

## Claim boundary

The current evidence covers five Developer workflows and fifteen functional executions per arm. It supports a scoped engineering claim, not a full Chat2Workflow leaderboard claim.
