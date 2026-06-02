from __future__ import annotations

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import DischargeSummaryAgent  # noqa: E402


def assert_contains(text: str, expected: str) -> None:
    if expected not in text:
        raise AssertionError(f"Expected to find {expected!r}")


def run_case(patient_id: str):
    agent = DischargeSummaryAgent()
    case = agent.run(patient_id)
    if not case.draft_markdown:
        raise AssertionError(f"{patient_id} did not produce a draft")
    if len(agent.trace.steps) > agent.max_steps:
        raise AssertionError(f"{patient_id} exceeded the step cap")
    return case, agent


def main() -> None:
    clean_case, clean_agent = run_case("mock_patient_001")
    assert_contains(clean_case.draft_markdown or "", "Draft for clinician review only")
    assert_contains(clean_case.draft_markdown or "", "lisinopril 20 mg PO daily: dose_changed - REVIEW REQUIRED")
    lisinopril = next(med for med in clean_case.discharge_medications if med.name == "lisinopril")
    if lisinopril.dose != "20 mg" or lisinopril.frequency != "daily":
        raise AssertionError("Structured medication parsing failed for lisinopril")

    missing_case, missing_agent = run_case("mock_patient_missing")
    draft = missing_case.draft_markdown or ""
    assert_contains(draft, "Missing expected source document: lab_results.")
    assert_contains(draft, "INR result pending")
    assert_contains(draft, "Warfarin and ibuprofen may increase bleeding risk.")
    ibuprofen = next(med for med in missing_case.discharge_medications if med.name == "ibuprofen")
    if ibuprofen.dose != "400 mg" or ibuprofen.frequency != "tid as needed":
        raise AssertionError("Structured medication parsing failed for ibuprofen")

    actions = [step.action for step in missing_agent.trace.steps]
    for required_action in [
        "load_source_documents",
        "extract_structured_facts",
        "verify_source_evidence",
        "extract_medications",
        "reconcile_medications",
        "drug_interaction_lookup",
        "escalate_for_clinician_review",
        "final_safety_validation",
        "draft_summary",
        "finish",
    ]:
        if required_action not in actions:
            raise AssertionError(f"Trace missing action {required_action}")

    print("Smoke tests passed")


if __name__ == "__main__":
    main()
