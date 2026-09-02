# ADR 0001: Use a specialized generator for bounded workflow configuration

- Status: accepted
- Date: 2026-09-02

## Context

General coding agents provide a broad action space that includes filesystem inspection, shell execution, dependency discovery, and arbitrary edits. Workflow configuration generation operates over a bounded node catalog, typed schemas, graph rules, and a known platform adapter.

The broad agent can solve the task, but it repeatedly carries context and capabilities that the configuration problem does not always need. A one-shot model call is cheaper for simple linear tasks, while complex branches benefit from staged context and deterministic feedback.

## Decision

Use a provider-independent specialized generator with selectable assurance profiles:

- direct generation for small linear tasks;
- staged Rewrite, Retrieve, Graph, and Bind generation;
- guarded validation and bounded repair for complex workflows;
- optional evidence-gated repair memory for repeated task families.

Keep the Dify adapter and execution harness separate from requirement semantics.

## Consequences

- Each stage has a smaller and auditable context.
- More model calls do not necessarily mean more processed tokens.
- The system must maintain explicit intermediate contracts.
- Stage boundaries introduce overhead on simple tasks.
- Open-ended coding and unknown plugin development remain outside the intended scope.
