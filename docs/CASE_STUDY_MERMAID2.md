# Case study: Mermaid_2

## Question

Can a domain-specific workflow generator use less model context than a general-purpose coding agent while producing a more useful executable result?

**Mermaid_2** is a two-round public Chat2Workflow task. The first requirement creates a system-architecture diagram from code documentation. The second adds a URL branch that chunks page content, summarizes the chunks, creates Mermaid mind-map source, renders the diagram, and merges branch outputs.

## Controlled setup

- Task: the same two accumulated public requirements.
- Model: **doubao-seed-evolving**.
- Thinking mode: disabled.
- Runtime: the same Dify deployment.
- Functional inputs: the same three fixed inputs.
- Generation memory: disabled.
- Evaluation: execution plus the same semantic-judge prompt.

## Generation accounting

### OpenCode Agentic

| Round | Processed tokens |
|---|---:|
| Initial architecture workflow | 16,609 |
| URL branch and merged outputs | 18,848 |
| **Total** | **35,457** |

The total includes uncached input, cache reads, and model output recorded by OpenCode. Cache reads may be billed differently by the provider, so this is a context-processing comparison rather than a currency-cost claim.

### WorkflowIR-Harness

| Stage | Prompt | Completion | Total |
|---|---:|---:|---:|
| Rewrite | 2,626 | 1,055 | 3,681 |
| Graph | 2,815 | 391 | 3,206 |
| Bind | 5,929 | 1,535 | 7,464 |
| Graph repair | 2,892 | 407 | 3,299 |
| Bind repair | 6,007 | 1,220 | 7,227 |
| **Total** | **20,269** | **4,608** | **24,877** |

The deterministic retriever, validators, adapter, and contract checks consume no model tokens.

## Outcome

| Method | Generation tokens | Model calls | Execution | Semantic success |
|---|---:|---:|---:|---:|
| OpenCode Agentic | 35,457 | 2 | 3/3 | 0/3 |
| WorkflowIR-Harness | **24,877** | 5 | 3/3 | **3/3** |

The harness used 10,580 fewer generation tokens, a 29.8% reduction in processed context.

## Why the executable OpenCode artifact still failed

The OpenCode workflow ran successfully, but its output contract was wrong:

~~~text
Expected
  summary      = prose knowledge summary
  mermaid_code = standalone Mermaid source

Observed
  summary      = missing or not exposed
  mermaid_code = prose summary + separator + Mermaid source
~~~

All three executions produced relevant content. All three failed semantic evaluation because the required non-file outputs were not separated correctly.

WorkflowIR-Harness treated output separation as a contract rather than as a formatting preference. After graph/binding repair and deterministic platform adaptation, all three inputs executed and passed semantic evaluation.

## Interpretation

This case supports three system claims:

1. Multiple small calls can process fewer tokens than a smaller number of broad-context calls.
2. Executability alone is insufficient when the output contract is wrong.
3. Typed failure feedback provides a more useful next action than unrestricted resampling.

It does not prove a 29.8% aggregate reduction across the benchmark. It is intentionally reported as a selected successful case; aggregate execution and semantic results are reported separately.
