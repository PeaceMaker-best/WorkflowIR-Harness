# Claims and limitations

## Supported claims

- A domain-specific staged generator can be combined with deterministic validation and bounded runtime repair.
- On 16 paired public benchmark workflows, the harness artifacts produced more stable runtime and semantic workflows under the disclosed engineering protocol.
- On the selected **Mermaid_2** task, the harness used 29.8% fewer processed generation tokens and passed all three semantic inputs.
- Runtime-visible feedback can be converted into typed repair evidence instead of unrestricted resampling.

## Unsupported claims

- This is not an official Chat2Workflow leaderboard result.
- The selected 29.8% token reduction is not an aggregate benchmark average.
- The evidence-gated experience pool has not yet demonstrated held-out online uplift.
- The current code does not automatically choose the optimal assurance profile.
- The project does not establish that specialized generators replace coding agents for open-ended programming tasks.

## Data boundary

Generation and repair may access the user requirement, public node documentation, selected node schemas, platform errors, node traces, and output-contract failures. They may not access reference workflows, judge answers, or hidden expected outputs.

Repair memory stores normalized failure signatures and generic policies. It excludes raw user input, complete model answers, API keys, URLs, emails, full traces, and benchmark ground truth.

## Corporate-project boundary

This repository is an independent follow-up implementation motivated by workflow-generation problems encountered in practice. It contains no proprietary company source code, API definitions, credentials, workflow exports, or business data.
