# Domain glossary

## Workflow generator

The probabilistic component that converts a requirement into Workflow IR. It may run as a direct generator or as the Rewrite, Retrieve, Graph, and Bind stages.

## Requirement contract

A user-confirmed semantic boundary containing the goal, inputs, outputs, constraints, and data dependencies. It is the shared source of truth for retrieval, generation, validation, and evaluation.

## Workflow IR

A platform-independent typed graph containing nodes, edges, variable references, and output contracts. Platform serialization fields are not part of its semantic core.

## Assurance harness

The deterministic and feedback-driven layer that validates Workflow IR, classifies import or runtime failures, selects a bounded repair scope, and requires a full rerun after repair.

## Assurance profile

A selectable amount of generation and verification support: **direct**, **staged**, **guarded**, or **adaptive**. A profile is not a quality level; it is a cost-risk trade-off chosen for a task.

## Validation issue

A typed observation in one of four failure layers: graph, binding, execution, or infrastructure. An issue describes evidence; it is not itself a repair instruction.

## Repair policy

A bounded mapping from a compatible validation issue to a repair action and repair scope.

## Experience pool

A task-isolated store of verified repair policies and their lifecycle evidence. It is not an answer cache and does not store benchmark ground truth.

## Stable workflow

One frozen workflow configuration that passes every fixed functional input assigned to it. A single successful execution is not a stable workflow.
