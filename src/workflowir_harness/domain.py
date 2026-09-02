from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence


class FailureLayer(str, Enum):
    GRAPH = "graph"
    BINDING = "binding"
    EXECUTION = "execution"
    INFRASTRUCTURE = "infrastructure"


class RepairScope(str, Enum):
    FULL_GRAPH = "full_graph"
    AFFECTED_NODE = "affected_node"
    SAME_REQUEST = "same_request"
    NONE = "none"


@dataclass(frozen=True)
class RequirementContract:
    goal: str
    inputs: Sequence[Mapping[str, Any]] = ()
    outputs: Sequence[Mapping[str, Any]] = ()
    constraints: Sequence[str] = ()
    data_dependencies: Sequence[str] = ()
    task_family: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowIR:
    nodes: List[Dict[str, Any]]
    edges: List[Sequence[Any]]
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    platform_extensions: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationIssue:
    layer: FailureLayer
    code: str
    message: str
    node_id: Optional[str] = None
    path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["layer"] = self.layer.value
        return value


@dataclass(frozen=True)
class RepairRequest:
    issues: Sequence[ValidationIssue]
    scope: RepairScope
    attempt: int
    use_experience: bool = False


@dataclass
class GenerationOutcome:
    workflow: WorkflowIR
    profile: str
    first_issues: Sequence[ValidationIssue]
    final_issues: Sequence[ValidationIssue]
    repairs: int
    usage: Dict[str, Any]

    @property
    def passed(self) -> bool:
        return not self.final_issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow": self.workflow.to_dict(),
            "profile": self.profile,
            "first_issues": [issue.to_dict() for issue in self.first_issues],
            "final_issues": [issue.to_dict() for issue in self.final_issues],
            "repairs": self.repairs,
            "passed": self.passed,
            "usage": self.usage,
        }
