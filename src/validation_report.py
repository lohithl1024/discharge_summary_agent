from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from schemas import CaseState
from tools import REQUIRED_FACTS


def build_validation_report(case: CaseState) -> dict[str, Any]:
    missing_fields = []
    pending_results = []
    conflicting_fields = []

    for name in REQUIRED_FACTS:
        fact = case.extracted_facts.get(name)
        if fact is None:
            missing_fields.append({"field": name, "reason": "fact_not_extracted"})
            continue
        if fact.status == "missing":
            missing_fields.append(
                {
                    "field": name,
                    "reason": "missing_from_source_documents",
                    "notes": fact.notes,
                }
            )
        elif fact.status == "pending":
            pending_results.append(
                {
                    "field": name,
                    "value": fact.value,
                    "evidence": [asdict(ev) for ev in fact.evidence],
                }
            )
        elif fact.status == "conflicting":
            conflicting_fields.append(
                {
                    "field": name,
                    "values": fact.value,
                    "evidence": [asdict(ev) for ev in fact.evidence],
                }
            )

    for metric in case.investigation_metrics:
        if metric.status == "pending":
            pending_results.append(
                {
                    "field": metric.name,
                    "value": metric.value,
                    "evidence": [asdict(ev) for ev in metric.evidence],
                }
            )

    return {
        "patient_id": case.patient_id,
        "source_paths": case.source_paths,
        "source_document_count": len(case.source_documents),
        "missing_documents": case.missing_documents,
        "missing_fields": missing_fields,
        "pending_results": pending_results,
        "conflicting_fields": conflicting_fields,
        "unsupported_facts_removed": case.unsupported_facts_removed,
        "medication_extraction": {
            "admission_medications": [medication_to_report(med) for med in case.admission_medications],
            "discharge_medications": [medication_to_report(med) for med in case.discharge_medications],
            "unclear_discharge_medications": [
                medication_to_report(med)
                for med in case.discharge_medications
                if med.status == "unclear"
            ],
        },
        "medication_changes": [
            {
                "medication_name": change.medication_name,
                "change_type": change.change_type,
                "documented_reason": change.documented_reason,
                "needs_review": change.needs_review,
                "notes": change.notes,
                "admission_med": medication_to_report(change.admission_med),
                "discharge_med": medication_to_report(change.discharge_med),
            }
            for change in case.medication_changes
        ],
        "safety_concerns": [asdict(concern) for concern in case.safety_concerns],
        "clinician_review_flags": case.clinician_review_flags,
        "final_safety_gate": {
            "passed": case.final_safety_passed,
            "blocking_errors": case.final_safety_blocking_errors,
            "warnings": case.final_safety_warnings,
        },
    }


def medication_to_report(medication) -> dict[str, Any] | None:
    if medication is None:
        return None
    return {
        "name": medication.name,
        "dose": medication.dose,
        "route": medication.route,
        "frequency": medication.frequency,
        "duration": medication.duration,
        "status": medication.status,
        "notes": medication.notes,
        "evidence": [asdict(ev) for ev in medication.evidence],
    }


def write_validation_report(case: CaseState, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_validation_report(case), indent=2),
        encoding="utf-8",
    )
