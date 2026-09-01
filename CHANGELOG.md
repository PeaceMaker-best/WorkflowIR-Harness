# Changelog

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
