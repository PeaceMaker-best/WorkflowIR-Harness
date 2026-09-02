from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class UsageRecord:
    stage: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    elapsed_seconds: float = 0.0
    attempt: int = 1
    success: bool = True

    @property
    def processed_tokens(self) -> int:
        return (
            self.prompt_tokens
            + self.completion_tokens
            + self.reasoning_tokens
            + self.cache_read_tokens
        )

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["processed_tokens"] = self.processed_tokens
        return value


class UsageLedger:
    def __init__(self, records: Iterable[UsageRecord] = ()) -> None:
        self._records: List[UsageRecord] = list(records)

    @property
    def records(self) -> List[UsageRecord]:
        return list(self._records)

    def add(self, record: UsageRecord | None) -> None:
        if record is not None:
            self._records.append(record)

    @property
    def processed_tokens(self) -> int:
        return sum(record.processed_tokens for record in self._records)

    def tokens_per_success(self, successful_workflows: int) -> float | None:
        if successful_workflows <= 0:
            return None
        return self.processed_tokens / successful_workflows

    def by_stage(self) -> Dict[str, int]:
        totals: Dict[str, int] = {}
        for record in self._records:
            totals[record.stage] = totals.get(record.stage, 0) + record.processed_tokens
        return totals

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_calls": len(self._records),
            "prompt_tokens": sum(record.prompt_tokens for record in self._records),
            "completion_tokens": sum(record.completion_tokens for record in self._records),
            "reasoning_tokens": sum(record.reasoning_tokens for record in self._records),
            "cache_read_tokens": sum(record.cache_read_tokens for record in self._records),
            "processed_tokens": self.processed_tokens,
            "elapsed_seconds": round(
                sum(record.elapsed_seconds for record in self._records), 6
            ),
            "by_stage": self.by_stage(),
            "calls": [record.to_dict() for record in self._records],
        }
