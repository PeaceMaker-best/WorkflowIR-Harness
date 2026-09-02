from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from .domain import (
    FailureLayer,
    GenerationOutcome,
    RepairRequest,
    RepairScope,
    RequirementContract,
    ValidationIssue,
    WorkflowIR,
)
from .profiles import AssuranceProfile
from .telemetry import UsageLedger, UsageRecord


@dataclass(frozen=True)
class StageResult:
    value: Any
    usage: Optional[UsageRecord] = None


@dataclass(frozen=True)
class PipelineComponents:
    direct: Optional[Callable[[str], StageResult]]
    rewrite: Callable[[str], StageResult]
    retrieve: Callable[[RequirementContract], Any]
    graph: Callable[[RequirementContract, Any], StageResult]
    bind: Callable[[RequirementContract, Any, Any], StageResult]
    validate: Callable[[WorkflowIR], Sequence[ValidationIssue]]
    repair: Optional[Callable[[WorkflowIR, RepairRequest], StageResult]] = None


def select_repair_scope(issues: Sequence[ValidationIssue]) -> RepairScope:
    layers = {issue.layer for issue in issues}
    if FailureLayer.GRAPH in layers:
        return RepairScope.FULL_GRAPH
    if layers & {FailureLayer.BINDING, FailureLayer.EXECUTION}:
        return RepairScope.AFFECTED_NODE
    if FailureLayer.INFRASTRUCTURE in layers:
        return RepairScope.SAME_REQUEST
    return RepairScope.NONE


class WorkflowPipeline:
    def __init__(
        self,
        components: PipelineComponents,
        max_repairs: int = 2,
    ) -> None:
        if max_repairs < 0:
            raise ValueError("max_repairs must be non-negative")
        self.components = components
        self.max_repairs = max_repairs

    @staticmethod
    def _workflow(value: Any, stage: str) -> WorkflowIR:
        if not isinstance(value, WorkflowIR):
            raise TypeError(f"{stage} must return WorkflowIR, got {type(value).__name__}")
        return value

    @staticmethod
    def _requirement(value: Any) -> RequirementContract:
        if not isinstance(value, RequirementContract):
            raise TypeError(
                "rewrite must return RequirementContract, "
                f"got {type(value).__name__}"
            )
        return value

    def run(
        self,
        requirement: str,
        profile: AssuranceProfile = AssuranceProfile.GUARDED,
    ) -> GenerationOutcome:
        ledger = UsageLedger()

        if not profile.uses_stages:
            if self.components.direct is None:
                raise ValueError("direct profile requires a direct generator")
            generated = self.components.direct(requirement)
            ledger.add(generated.usage)
            workflow = self._workflow(generated.value, "direct")
        else:
            rewritten = self.components.rewrite(requirement)
            ledger.add(rewritten.usage)
            contract = self._requirement(rewritten.value)

            candidates = self.components.retrieve(contract)

            graphed = self.components.graph(contract, candidates)
            ledger.add(graphed.usage)

            bound = self.components.bind(contract, graphed.value, candidates)
            ledger.add(bound.usage)
            workflow = self._workflow(bound.value, "bind")

        issues = tuple(self.components.validate(workflow))
        first_issues = issues
        repairs = 0

        while (
            issues
            and repairs < self.max_repairs
            and profile.allows_repair
            and self.components.repair is not None
        ):
            request = RepairRequest(
                issues=issues,
                scope=select_repair_scope(issues),
                attempt=repairs + 1,
                use_experience=profile.uses_experience,
            )
            repaired = self.components.repair(workflow, request)
            ledger.add(repaired.usage)
            workflow = self._workflow(repaired.value, "repair")
            repairs += 1
            issues = tuple(self.components.validate(workflow))

        return GenerationOutcome(
            workflow=workflow,
            profile=profile.value,
            first_issues=first_issues,
            final_issues=issues,
            repairs=repairs,
            usage=ledger.to_dict(),
        )
