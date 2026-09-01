# Bad cases and harness upgrades

The harness was upgraded from observed failures rather than by adding a generic retry loop.

| Case | Observed failure | Root cause | Directed repair | Boundary |
|---|---|---|---|---|
| `Code_2` | Official arm executed 0/3 inputs | Generated non-Python code and unrestricted assumptions were passed to a Python sandbox | Detect the language contract, translate to Python 3, bind the case input, enforce a sandbox-safe runtime contract, and feed a bounded node trace into at most two retries | No arbitrary package installation; unsupported programs are rejected |
| `Code_3` | Runtime-only workflow executed but semantic success was 0/3 before requirement repair | The graph ran, but it did not satisfy the requested source-code explanation contract | Add a language-agnostic source-analysis gate and an explicit explanation contract | Markdown fallback is a typed artifact descriptor, not a native file |
| `Mermaid_2` | Official arm executed 3/3 but output-contract and semantic success were 0/3 | Iterator/aggregator output types did not match the final contract | Infer runtime types, normalize aggregator aliases, and validate branch/output closure before execution | The raw harness run still recorded one plugin-database infrastructure failure |
| `Code_1` | Official semantic success was 2/3 | One output violated the requested staged translation semantics despite a successful run | Keep structural translation and final implementation contracts separate | Semantic judge variance remains a threat; retain the per-input verdict |

## Failure taxonomy

- **Graph**: dangling edge, missing node, illegal connection, cycle where disallowed, or incomplete Router/Merge closure.
- **Binding**: missing variable, wrong selector, type mismatch, or output contract mismatch.
- **Execution**: a concrete node fails after the graph and bindings are valid.
- **Infrastructure**: model/provider/database/plugin availability failure outside workflow semantics.

## Repair policy

1. Graph failures rebuild the topology skeleton; the harness does not guess a missing edge inside a corrupted graph.
2. Binding failures rebind only the affected node and then run whole-graph validation.
3. Execution failures receive the failing node's bounded trace. At most two directed retries are allowed.
4. Infrastructure failures use a separate retry budget and never consume the semantic repair budget.
5. After any repair, the complete graph is revalidated and rerun.
6. When the node count or unsupported capability exceeds the declared envelope, return an explicit unsupported result instead of looping.

## Development-set recovery evidence

- `Code_3`: semantic task success improved from 0/3 with runtime-only adaptation to 3/3 after requirement-contract repair.
- `Code_2`: final harness run reached 3/3 semantic success; an earlier debug run demonstrated a trace-directed recovery on N-Queens.
- `Mermaid_2`: official arm was 0/3 on output contract and semantics; harness arm was 2/3 in the raw run and 3/3 after rerunning the exact infrastructure-only failure.

These are post-hoc repair results on known bad cases. They demonstrate regression closure, not unseen-test generalization.
