from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


FactStatus = Literal["present", "missing", "pending", "conflicting"]
MedicationChangeType = Literal[
    "continued",
    "added",
    "stopped",
    "dose_changed",
    "frequency_changed",
    "unclear",
]


@dataclass
class Evidence:
    source_id: str
    quote: str


@dataclass
class ClinicalFact:
    name: str
    value: Any = None
    status: FactStatus = "missing"
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Medication:
    name: str
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    duration: str | None = None
    status: Literal["structured", "unclear"] = "structured"
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class MedicationChange:
    medication_name: str
    change_type: MedicationChangeType
    admission_med: Medication | None = None
    discharge_med: Medication | None = None
    documented_reason: str | None = None
    needs_review: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class InvestigationMetric:
    name: str
    value: str
    unit: str | None = None
    reference_range: str | None = None
    status: Literal["present", "pending", "abnormal", "unclear"] = "present"
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class SafetyConcern:
    category: str
    description: str
    severity: Literal["low", "medium", "high"]
    evidence: list[Evidence] = field(default_factory=list)
    escalated: bool = False


@dataclass
class CaseState:
    patient_id: str
    source_paths: list[str] = field(default_factory=list)
    source_documents: dict[str, str] = field(default_factory=dict)
    expected_documents: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    extracted_facts: dict[str, ClinicalFact] = field(default_factory=dict)
    admission_medications: list[Medication] = field(default_factory=list)
    discharge_medications: list[Medication] = field(default_factory=list)
    medication_changes: list[MedicationChange] = field(default_factory=list)
    investigation_metrics: list[InvestigationMetric] = field(default_factory=list)
    safety_concerns: list[SafetyConcern] = field(default_factory=list)
    clinician_review_flags: list[str] = field(default_factory=list)
    draft_markdown: str | None = None
    unsupported_facts_removed: list[str] = field(default_factory=list)
    final_safety_passed: bool = False
    final_safety_warnings: list[str] = field(default_factory=list)
    final_safety_blocking_errors: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    completed_actions: set[str] = field(default_factory=set)
    tool_attempts: dict[str, int] = field(default_factory=dict)
    max_retries_per_tool: int = 2


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    retryable: bool = False


@dataclass
class TraceStep:
    step: int
    reasoning: str
    action: str
    inputs: dict[str, Any]
    result: dict[str, Any]
    next_decision: str


@dataclass
class PlannerDecision:
    reasoning: str
    action: str
    tool: Callable[[CaseState], ToolResult] | None
    inputs: dict[str, Any]
    next_decision: str
