from workflowir_harness import (
    AssuranceProfile,
    FailureLayer,
    PipelineComponents,
    RepairScope,
    RequirementContract,
    StageResult,
    UsageRecord,
    ValidationIssue,
    WorkflowIR,
    WorkflowPipeline,
)
from workflowir_harness.pipeline import select_repair_scope


def usage(stage: str, prompt: int, completion: int) -> UsageRecord:
    return UsageRecord(
        stage=stage,
        prompt_tokens=prompt,
        completion_tokens=completion,
    )


def rewrite(_: str) -> StageResult:
    return StageResult(
        RequirementContract(
            goal="Generate a stable workflow",
            inputs=({"name": "query", "type": "string"},),
            outputs=({"name": "result", "type": "string"},),
        ),
        usage("rewrite", 100, 20),
    )


def retrieve(_: RequirementContract):
    return ("start", "llm", "end")


def graph(_: RequirementContract, __):
    return StageResult(
        {"nodes": ["start", "llm", "end"], "edges": [["start", "llm"], ["llm", "end"]]},
        usage("graph", 200, 30),
    )


def bind(_: RequirementContract, __, ___) -> StageResult:
    return StageResult(
        WorkflowIR(
            nodes=[{"id": "1", "type": "start"}, {"id": "2", "type": "end"}],
            edges=[["1", 0, "2"]],
            metadata={"revision": 0},
        ),
        usage("bind", 300, 40),
    )


def direct(_: str) -> StageResult:
    return StageResult(
        WorkflowIR(
            nodes=[{"id": "1", "type": "start"}, {"id": "2", "type": "end"}],
            edges=[["1", 0, "2"]],
            metadata={"revision": 1},
        ),
        usage("direct", 90, 10),
    )


def validate(workflow: WorkflowIR):
    if workflow.metadata.get("revision") == 0:
        return [
            ValidationIssue(
                layer=FailureLayer.GRAPH,
                code="EDGE_ENDPOINT_NOT_FOUND",
                message="edge target is missing",
            )
        ]
    return []


def repair(workflow: WorkflowIR, request) -> StageResult:
    assert request.scope is RepairScope.FULL_GRAPH
    assert request.use_experience is True
    workflow.metadata["revision"] = 1
    return StageResult(workflow, usage("graph_repair", 150, 25))


components = PipelineComponents(
    direct=direct,
    rewrite=rewrite,
    retrieve=retrieve,
    graph=graph,
    bind=bind,
    validate=validate,
    repair=repair,
)

guarded = WorkflowPipeline(components).run(
    "build a workflow",
    profile=AssuranceProfile.ADAPTIVE,
)
assert guarded.passed
assert guarded.repairs == 1
assert guarded.usage["model_calls"] == 4
assert guarded.usage["processed_tokens"] == 865
assert guarded.usage["by_stage"]["graph_repair"] == 175

direct_result = WorkflowPipeline(components).run(
    "build a workflow",
    profile=AssuranceProfile.DIRECT,
)
assert direct_result.passed
assert direct_result.repairs == 0
assert direct_result.usage["processed_tokens"] == 100

assert (
    select_repair_scope(
        [
            ValidationIssue(
                layer=FailureLayer.INFRASTRUCTURE,
                code="PROVIDER_TIMEOUT",
                message="provider timed out",
            )
        ]
    )
    is RepairScope.SAME_REQUEST
)

print("pipeline self-test passed")
