from __future__ import annotations

from dataclasses import asdict

from schemas import CaseState, PlannerDecision, ToolResult
from pdf_ingestion import ingest_pdf_documents
from tools import (
    REQUIRED_FACTS,
    draft_summary,
    drug_interaction_lookup,
    escalate_for_clinician_review,
    extract_investigation_metrics,
    extract_medications,
    final_safety_validation,
    extract_structured_facts,
    fallback_document_report,
    load_source_documents,
    reconcile_medications,
    verify_source_evidence,
)
from trace import TraceRecorder


MAX_STEPS = 14


class DischargeSummaryAgent:
    def __init__(self, max_steps: int = MAX_STEPS) -> None:
        self.max_steps = max_steps
        self.trace = TraceRecorder()

    def run(self, patient_id: str, source_paths: list[str] | None = None) -> CaseState:
        case = CaseState(patient_id=patient_id, source_paths=source_paths or [])

        for step in range(1, self.max_steps + 1):
            decision = self._plan_next_action(case)

            if decision.action == "finish":
                self.trace.add(
                    step=step,
                    reasoning=decision.reasoning,
                    action=decision.action,
                    inputs=decision.inputs,
                    result={"ok": True, "message": "Agent finished."},
                    next_decision=decision.next_decision,
                )
                return case

            result = self._call_tool_safely(decision.action, decision.tool, case)
            if result.ok:
                case.completed_actions.add(decision.action)

            self.trace.add(
                step=step,
                reasoning=decision.reasoning,
                action=decision.action,
                inputs=decision.inputs,
                result=asdict(result),
                next_decision=self._next_decision_after_tool(case, decision, result),
            )

        case.clinician_review_flags.append(
            f"Agent stopped after hard cap of {self.max_steps} steps. Clinician review required."
        )
        return case

    def _plan_next_action(self, case: CaseState) -> PlannerDecision:
        if not case.source_documents:
            if case.source_paths:
                if self._can_retry(case, "ingest_pdf_documents"):
                    return PlannerDecision(
                        reasoning=(
                            "PDF source paths were provided. The agent should ingest OCR/PDF text "
                            "into page-level source documents before extracting facts."
                        ),
                        action="ingest_pdf_documents",
                        tool=ingest_pdf_documents,
                        inputs={"source_paths": case.source_paths},
                        next_decision="Extract structured facts from PDF text and inspect missing text.",
                    )
                return PlannerDecision(
                    reasoning=(
                        "PDF ingestion failed. The agent must report the failure rather than "
                        "behaving as if documents were read."
                    ),
                    action="fallback_document_report",
                    tool=fallback_document_report,
                    inputs={"source_paths": case.source_paths, "failed_tools": case.failed_tools},
                    next_decision="Flag unavailable documents for clinician review.",
                )

            if self._can_retry(case, "load_source_documents"):
                return PlannerDecision(
                    reasoning=(
                        "No source documents are available. The agent must obtain source text "
                        "before extracting any clinical facts."
                    ),
                    action="load_source_documents",
                    tool=load_source_documents,
                    inputs={"patient_id": case.patient_id},
                    next_decision="Inspect loaded documents and identify missing or empty notes.",
                )
            return PlannerDecision(
                reasoning=(
                    "Document loading failed or was unavailable. The agent must report what is "
                    "missing instead of pretending extraction succeeded."
                ),
                action="fallback_document_report",
                tool=fallback_document_report,
                inputs={"patient_id": case.patient_id, "failed_tools": case.failed_tools},
                next_decision="Continue only with any available source text and flag missing documents.",
            )

        if not case.extracted_facts:
            return PlannerDecision(
                reasoning=(
                    "Source text exists, but required discharge-summary fields have not been "
                    "extracted. The next tool should extract structured facts with evidence."
                ),
                action="extract_structured_facts",
                tool=extract_structured_facts,
                inputs=self._document_input_summary(case),
                next_decision="Verify evidence before using extracted facts.",
            )

        if "verify_source_evidence" not in case.completed_actions:
            return PlannerDecision(
                reasoning=(
                    "Clinical facts must be source-supported. The guardrail should remove or "
                    "downgrade any present fact that lacks evidence."
                ),
                action="verify_source_evidence",
                tool=verify_source_evidence,
                inputs={"facts": list(case.extracted_facts)},
                next_decision="Plan around missing, pending, or supported facts only.",
            )

        if "extract_investigation_metrics" not in case.completed_actions:
            return PlannerDecision(
                reasoning=(
                    "The source packet may contain lab and investigation metrics. The agent should "
                    "extract source-supported values and pending results before drafting."
                ),
                action="extract_investigation_metrics",
                tool=extract_investigation_metrics,
                inputs=self._document_input_summary(case),
                next_decision="Use extracted metrics as evidence and flag pending investigations.",
            )

        if self._required_fact_gap(case) and "escalate_for_clinician_review" not in case.completed_actions:
            return PlannerDecision(
                reasoning=(
                    "Some required fields are missing, pending, or conflicting. The agent should "
                    "not infer values; it must create clinician-review flags."
                ),
                action="escalate_for_clinician_review",
                tool=escalate_for_clinician_review,
                inputs={"problem_fields": self._required_fact_gap(case)},
                next_decision="Continue with other tools while preserving the review flags.",
            )

        if (
            not case.admission_medications
            and not case.discharge_medications
            and "extract_medications" not in case.completed_actions
            and self._can_retry(case, "extract_medications")
        ):
            return PlannerDecision(
                reasoning=(
                    "Medication reconciliation is required. The agent needs separate admission "
                    "and discharge medication lists before comparing changes."
                ),
                action="extract_medications",
                tool=extract_medications,
                inputs=self._document_input_summary(case),
                next_decision="Compare admission and discharge medication lists.",
            )

        if not case.medication_changes:
            return PlannerDecision(
                reasoning=(
                    "Medication lists have been extracted. The agent must compare them and flag "
                    "added, stopped, dose-changed, or unclear medications without documented reasons."
                ),
                action="reconcile_medications",
                tool=reconcile_medications,
                inputs={
                    "admission_medications": len(case.admission_medications),
                    "discharge_medications": len(case.discharge_medications),
                },
                next_decision="Decide whether a safety lookup or escalation is needed.",
            )

        if "drug_interaction_lookup" not in case.completed_actions and case.discharge_medications:
            return PlannerDecision(
                reasoning=(
                    "Discharge medications are available. The agent should decide whether to use "
                    "the mocked safety tool to surface interactions instead of burying them."
                ),
                action="drug_interaction_lookup",
                tool=drug_interaction_lookup,
                inputs={"discharge_medications": [med.name for med in case.discharge_medications]},
                next_decision="Escalate any medication changes or safety concerns.",
            )

        if self._needs_escalation(case):
            return PlannerDecision(
                reasoning=(
                    "There are unresolved missing fields, medication reconciliation issues, or "
                    "safety concerns. These must be escalated before drafting."
                ),
                action="escalate_for_clinician_review",
                tool=escalate_for_clinician_review,
                inputs={
                    "fact_gaps": self._required_fact_gap(case),
                    "medication_review_items": [
                        change.medication_name
                        for change in case.medication_changes
                        if change.needs_review
                    ],
                    "safety_concerns": [concern.description for concern in case.safety_concerns],
                },
                next_decision="Draft only after flags are visible in the case state.",
            )

        if "final_safety_validation" not in case.completed_actions:
            return PlannerDecision(
                reasoning=(
                    "Before drafting, the agent must verify that present facts have evidence and "
                    "that missing, pending, conflicting, medication, and safety issues are flagged."
                ),
                action="final_safety_validation",
                tool=final_safety_validation,
                inputs={
                    "facts": len(case.extracted_facts),
                    "review_flags": len(case.clinician_review_flags),
                    "medication_changes": len(case.medication_changes),
                    "safety_concerns": len(case.safety_concerns),
                },
                next_decision="Draft only if the final safety gate passes.",
            )

        if case.draft_markdown is None:
            return PlannerDecision(
                reasoning=(
                    "All available source-supported facts have been collected and unresolved "
                    "items have been flagged. The agent can now produce a draft for review."
                ),
                action="draft_summary",
                tool=draft_summary,
                inputs={"patient_id": case.patient_id},
                next_decision="Finish if the draft is generated successfully.",
            )

        return PlannerDecision(
            reasoning="A draft exists and all required safety checks have run.",
            action="finish",
            tool=None,
            inputs={"patient_id": case.patient_id},
            next_decision="Return draft and trace.",
        )

    def _call_tool_safely(self, action: str, tool_fn, case: CaseState) -> ToolResult:
        case.tool_attempts[action] = case.tool_attempts.get(action, 0) + 1
        if tool_fn is None:
            return ToolResult(ok=False, error=f"No tool registered for action {action}.")

        try:
            result = tool_fn(case)
        except Exception as exc:
            result = ToolResult(ok=False, error=str(exc), retryable=True)

        if not result.ok:
            case.failed_tools.append(action)
        return result

    def _next_decision_after_tool(
        self, case: CaseState, decision: PlannerDecision, result: ToolResult
    ) -> str:
        if result.ok:
            return decision.next_decision
        if result.retryable and self._can_retry(case, decision.action):
            return f"Retry {decision.action}; previous attempt failed safely."
        return "Do not assume success. Re-plan with fallback or clinician-review reporting."

    def _can_retry(self, case: CaseState, action: str) -> bool:
        return case.tool_attempts.get(action, 0) < case.max_retries_per_tool

    def _required_fact_gap(self, case: CaseState) -> list[str]:
        gaps = []
        for name in REQUIRED_FACTS:
            fact = case.extracted_facts.get(name)
            if fact is None or fact.status in {"missing", "pending", "conflicting"}:
                gaps.append(name)
        return gaps

    def _needs_escalation(self, case: CaseState) -> bool:
        if "escalate_for_clinician_review" not in case.completed_actions:
            return True

        for missing_doc in case.missing_documents:
            if not self._flag_exists(case, f"Missing expected source document: {missing_doc}."):
                return True

        for gap in self._required_fact_gap(case):
            fact = case.extracted_facts.get(gap)
            status = fact.status if fact else "missing"
            if not self._flag_exists(case, f"{gap}: {status}. Clinician review required."):
                return True

        for change in case.medication_changes:
            if change.needs_review and not any(
                flag.startswith(f"Medication reconciliation: {change.medication_name} ")
                for flag in case.clinician_review_flags
            ):
                return True

        if any(not concern.escalated for concern in case.safety_concerns):
            return True

        return False

    def _flag_exists(self, case: CaseState, expected_flag: str) -> bool:
        return expected_flag in case.clinician_review_flags

    def _document_input_summary(self, case: CaseState) -> dict[str, object]:
        names = list(case.source_documents)
        return {
            "document_count": len(names),
            "sample_documents": names[:5],
            "has_combined_text": any(name.endswith("_combined_text") for name in names),
        }
