# Changelog

## v0.3.0 — 2026-09-02

- Expanded the custom runtime study to 19 harness workflows and 57 fixed-input trials.
- Added paired runtime and Resolve-stage semantic reporting for 16 workflows with official artifacts.
- Added deterministic ECharts array-to-delimited-text adaptation.
- Added Dify-compatible multi-file upload handling.
- Added a typed Iteration fan-out budget guard.
- Added successful-trial resume and cold sample-level parallelism.

The expanded run keeps the experience pool disabled. No self-evolving uplift is claimed.

## v0.2.0 — 2026-09-02

- Added conservative candidate, active, and quarantined policy states.
- Added evidence-gated promotion using whole-graph success and Wilson reliability.
- Added automatic quarantine after consecutive policy failures.
- Added version lineage for recovery from quarantined policies.
- Added append-only lifecycle events and release-safe statistics.
- Prevented duplicate success counting when a retrieved policy repairs a trial.
- Integrated configurable self-evolution gates into the Dify runner.
- Added migration and deterministic lifecycle regressions.

The v0.2 lifecycle is validated offline. No online success-rate uplift is claimed
until a new cold/candidate/warm execution experiment is completed.

## v0.1.0 — 2026-09-02

- Initial contract-guided workflow validation and repair harness.
- Task-scoped runtime experience storage.
- Frozen five-workflow developer evaluation and infrastructure-retry audit.
