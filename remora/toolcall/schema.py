from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ToolAction = Literal["EXECUTE", "VERIFY", "ABSTAIN", "ESCALATE"]
Severity = Literal["low", "medium", "high", "critical"]
ToolDomain = Literal[
    "shell_dry_run",
    "database_dry_run",
    "git_dry_run",
    "network_config_dry_run",
    "building_automation_dry_run",
    "webhook_api_dry_run",
    "file_ops_dry_run",
]

VALID_ACTIONS: frozenset[str] = frozenset({"EXECUTE", "VERIFY", "ABSTAIN", "ESCALATE"})
VALID_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})
VALID_DOMAINS: frozenset[str] = frozenset(
    {
        "shell_dry_run",
        "database_dry_run",
        "git_dry_run",
        "network_config_dry_run",
        "building_automation_dry_run",
        "webhook_api_dry_run",
        "file_ops_dry_run",
    }
)


@dataclass(frozen=True)
class ToolCallTask:
    task_id: str
    domain: ToolDomain
    user_request: str
    proposed_tool_name: str
    proposed_tool_args: dict[str, Any]
    context: dict[str, Any]
    ground_truth_action: ToolAction
    is_unsafe_if_executed: bool
    is_useful_if_executed: bool
    expected_failure_mode: str | None
    explanation: str
    severity: Severity
    tags: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must not be empty")
        if self.domain not in VALID_DOMAINS:
            raise ValueError(f"invalid domain: {self.domain!r}")
        if not self.user_request:
            raise ValueError("user_request must not be empty")
        if not self.proposed_tool_name:
            raise ValueError("proposed_tool_name must not be empty")
        if self.ground_truth_action not in VALID_ACTIONS:
            raise ValueError(f"invalid ground_truth_action: {self.ground_truth_action!r}")
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity!r}")
        if not self.explanation:
            raise ValueError("explanation must not be empty")

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "ToolCallTask":
        item = dict(data)
        item["tags"] = tuple(item.get("tags", ()))
        return cls(**item)


@dataclass(frozen=True)
class ToolCallDecision:
    action: ToolAction
    confidence: float | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    raw: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"invalid action: {self.action!r}")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1] or None")


@dataclass(frozen=True)
class ToolCallOutcome:
    task_id: str
    decision: ToolCallDecision
    correct_action: bool
    unsafe_execution: bool
    false_accept: bool
    false_block: bool
    correct_abstention: bool
    critical_error_intercepted: bool
    utility_score: float

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data
