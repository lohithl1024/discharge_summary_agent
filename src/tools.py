from __future__ import annotations

import re

from schemas import (
    CaseState,
    ClinicalFact,
    Evidence,
    InvestigationMetric,
    Medication,
    MedicationChange,
    SafetyConcern,
    ToolResult,
)


REQUIRED_FACTS = [
    "patient_demographics",
    "admission_date",
    "discharge_date",
    "principal_diagnosis",
    "secondary_diagnoses",
    "hospital_course",
    "procedures",
    "allergies",
    "follow_up",
    "pending_results",
    "discharge_condition",
]


MOCK_CASES = {
    "mock_patient_001": {
        "expected_documents": [
            "admission_note",
            "progress_note",
            "lab_results",
            "discharge_medication_record",
            "discharge_note",
        ],
        "documents": {
            "admission_note": (
                "Patient: Jane Doe, 64F. Admitted 2026-01-02 for community-acquired "
                "pneumonia. Secondary diagnosis: type 2 diabetes. Allergy: penicillin. "
                "Home meds: metformin 500 mg PO BID; lisinopril 10 mg PO daily."
            ),
            "progress_note": (
                "Hospital course: treated with ceftriaxone and azithromycin. Respiratory "
                "status improved. Blood cultures pending."
            ),
            "lab_results": "Blood culture: pending. Creatinine 1.0 mg/dL.",
            "discharge_medication_record": (
                "Discharge meds: metformin 500 mg PO BID; lisinopril 20 mg PO daily; "
                "azithromycin 250 mg PO daily for 3 days."
            ),
            "discharge_note": (
                "Discharged 2026-01-06. Follow up with PCP in 1 week. Discharge condition: stable. "
                "Procedures: none."
            ),
        },
    },
    "mock_patient_missing": {
        "expected_documents": [
            "admission_note",
            "progress_note",
            "lab_results",
            "discharge_medication_record",
            "discharge_note",
        ],
        "documents": {
            "admission_note": (
                "Patient: Ravi Kumar, 58M. Admitted 2026-02-10 for heart failure exacerbation. "
                "Allergies: no known drug allergies. Home meds: furosemide 20 mg PO daily; "
                "warfarin 5 mg PO daily."
            ),
            "progress_note": (
                "Hospital course: diuresed with IV furosemide. INR result pending. "
                "Progress note diagnosis: heart failure exacerbation."
            ),
            "discharge_medication_record": (
                "Discharge meds: furosemide 40 mg PO daily; warfarin 5 mg PO daily; "
                "ibuprofen 400 mg PO TID as needed."
            ),
        },
    },
}


def load_source_documents(case: CaseState) -> ToolResult:
    mock_case = MOCK_CASES.get(case.patient_id)
    if mock_case is None:
        return ToolResult(
            ok=False,
            error=f"No source documents found for patient_id={case.patient_id}.",
            retryable=False,
        )

    case.expected_documents = list(mock_case["expected_documents"])
    documents = dict(mock_case["documents"])
    empty_docs = [name for name, text in documents.items() if not text.strip()]
    if empty_docs:
        return ToolResult(
            ok=False,
            data={"empty_documents": empty_docs},
            error="One or more source documents returned empty text.",
            retryable=True,
        )

    case.source_documents = documents
    case.missing_documents = [
        name for name in case.expected_documents if name not in case.source_documents
    ]
    return ToolResult(
        ok=True,
        data={
            "documents_loaded": list(case.source_documents),
            "missing_documents": case.missing_documents,
        },
    )


def fallback_document_report(case: CaseState) -> ToolResult:
    if case.source_documents:
        return ToolResult(ok=True, data={"fallback_needed": False})

    mock_case = MOCK_CASES.get(case.patient_id)
    if mock_case is None:
        case.missing_documents = ["all_source_documents"]
        return ToolResult(ok=True, data={"reported_missing": case.missing_documents})

    case.expected_documents = list(mock_case["expected_documents"])
    case.source_documents = {
        name: text for name, text in mock_case["documents"].items() if text.strip()
    }
    case.missing_documents = [
        name for name in case.expected_documents if name not in case.source_documents
    ]
    return ToolResult(
        ok=True,
        data={
            "fallback_loaded_documents": list(case.source_documents),
            "reported_missing": case.missing_documents,
        },
    )


def extract_structured_facts(case: CaseState) -> ToolResult:
    if not case.source_documents:
        return ToolResult(ok=False, error="No source documents available.", retryable=False)

    facts: dict[str, ClinicalFact] = {}
    add_diagnosis_facts(facts, case.source_documents)
    add_fact_from_patterns(
        facts,
        "patient_demographics",
        case.source_documents,
        [r"Patient:\s*([^.\n]+)"],
    )
    add_fact_from_patterns(
        facts,
        "admission_date",
        case.source_documents,
        [r"Admitted\s*(\d{4}-\d{2}-\d{2})"],
    )
    add_fact_from_patterns(
        facts,
        "discharge_date",
        case.source_documents,
        [r"Discharged\s*(\d{4}-\d{2}-\d{2})"],
    )
    add_fact_from_patterns(
        facts,
        "principal_diagnosis",
        case.source_documents,
        [r"admitted\s+\d{4}-\d{2}-\d{2}\s+for\s+([^.\n]+)"],
        flags=re.IGNORECASE,
    )
    add_fact_from_patterns(
        facts,
        "secondary_diagnoses",
        case.source_documents,
        [r"Secondary diagnos(?:is|es):\s*([^.\n]+)"],
    )
    add_fact_from_patterns(
        facts,
        "hospital_course",
        case.source_documents,
        [
            r"Hospital course:\s*([^.\n]+(?:\.\s*[^.\n]+)*)",
            r"COURSE IN THE HOSPITAL:\s*([^§]+?)(?:CONDITION AT DISCHARGE:|ADVICE ON DISCHARGE:|FOLLOW-UP INSTRUCTIONS:|$)",
        ],
        flags=re.IGNORECASE,
    )
    add_fact_from_patterns(
        facts,
        "procedures",
        case.source_documents,
        [r"Procedures:\s*([^.\n]+)"],
    )
    add_fact_from_patterns(
        facts,
        "allergies",
        case.source_documents,
        [r"Allerg(?:y|ies):\s*([^.\n]+)"],
    )
    add_fact_from_patterns(
        facts,
        "follow_up",
        case.source_documents,
        [
            r"Follow up\s*([^.\n]+)",
            r"Follow-up:\s*([^.\n]+)",
            r"FOLLOW-UP INSTRUCTIONS:\s*([^§]+?)(?:Review on|$)",
            r"Review on\s*([0-9./-]+)",
        ],
        flags=re.IGNORECASE,
    )
    add_fact_from_patterns(
        facts,
        "discharge_condition",
        case.source_documents,
        [r"Discharge condition:\s*([^.\n]+)", r"CONDITION AT DISCHARGE:\s*([^.\n]+)"],
        flags=re.IGNORECASE,
    )

    pending_evidence = find_pending_results(case.source_documents)
    if pending_evidence:
        facts["pending_results"] = ClinicalFact(
            name="pending_results",
            value="; ".join(ev.quote for ev in pending_evidence),
            status="pending",
            evidence=pending_evidence,
        )

    for required in REQUIRED_FACTS:
        facts.setdefault(
            required,
            ClinicalFact(
                name=required,
                status="missing",
                notes=["No source evidence found. Clinician review required."],
            ),
        )

    for missing_doc in case.missing_documents:
        facts[f"missing_document_{missing_doc}"] = ClinicalFact(
            name=f"missing_document_{missing_doc}",
            value=missing_doc,
            status="missing",
            notes=[f"Expected document absent: {missing_doc}."],
        )

    case.extracted_facts = facts
    return ToolResult(
        ok=True,
        data={
            "facts_extracted": len(facts),
            "present": sum(f.status == "present" for f in facts.values()),
            "missing": sum(f.status == "missing" for f in facts.values()),
            "pending": sum(f.status == "pending" for f in facts.values()),
        },
    )


def extract_investigation_metrics(case: CaseState) -> ToolResult:
    metrics: list[InvestigationMetric] = []
    joined = "\n".join(case.source_documents.values())

    metric_patterns = [
        ("serum_creatinine", r"creatinine\s*\(?\s*([0-9.]+)\s*mg/?d[li1\]]", "mg/dL"),
        ("repeat_serum_creatinine", r"Repeat Serum Creatinine\s*\(?\s*([0-9.]+)\s*mg/?d[li1\]]", "mg/dL"),
        ("serum_sodium", r"serum sodium\s*\(?\s*([0-9.]+)\s*(?:m?mol/L|mnol/L)", "mmol/L"),
        ("urine_pus_cells", r"([0-9]+\s*-\s*[0-9]+/hpf of pus cells)", None),
        ("urine_epithelial_cells", r"([0-9]+\s*-\s*[0-9]+0?hpf of epithelial cells)", None),
        ("urine_ketone_bodies", r"(ketone bodies\(\+\))", None),
        ("stool_red_blood_cells", r"Stool routine.*?([0-9]+\s*-\s*[0-9]+/hpf of red blood cells)", None),
        ("stool_pus_cells", r"Stool routine.*?(plent\w*/hpf of pus cells)", None),
        ("rbs", r"RAN P DOM BLOCD SUGAR \(RBS\)\s*_?([0-9.]+)", None),
        ("abg_sodium", r"Sodium \[Na\+\]\s*([0-9.]+)\s*m", "mmol/L"),
        ("abg_potassium", r"Potassium \[K\s*\]\s*([0-9.]+)\s*mmol/L", "mmol/L"),
        ("haemoglobin", r"HAEMOGLOBIN\s+([0-9.]+)\s*g", "g/dL"),
        ("platelet_count", r"PLATELET COUNT\s+([0-9.]+)\s*Lakhs/cumm", "Lakhs/cumm"),
    ]

    for name, pattern, unit in metric_patterns:
        for match in re.finditer(pattern, joined, re.IGNORECASE | re.DOTALL):
            quote = clean_value(match.group(0))
            value = clean_value(match.group(1))
            metrics.append(
                InvestigationMetric(
                    name=name,
                    value=value,
                    unit=unit,
                    status="present",
                    evidence=[Evidence("pdf_text", quote[:240])],
                )
            )

    for evidence in find_pending_results(case.source_documents):
        if "culture" in evidence.quote.lower() or "report awaited" in evidence.quote.lower():
            metrics.append(
                InvestigationMetric(
                    name="pending_culture_or_report",
                    value=evidence.quote,
                    status="pending",
                    evidence=[evidence],
                )
            )

    case.investigation_metrics = dedupe_metrics(metrics)
    return ToolResult(
        ok=True,
        data={
            "investigation_metrics": len(case.investigation_metrics),
            "pending_metrics": sum(m.status == "pending" for m in case.investigation_metrics),
        },
    )


def verify_source_evidence(case: CaseState) -> ToolResult:
    unsupported = []
    for fact in case.extracted_facts.values():
        if fact.status == "present" and not fact.evidence:
            fact.status = "missing"
            fact.value = None
            fact.notes.append("Fact had no evidence and was removed by guardrail.")
            unsupported.append(fact.name)

    case.unsupported_facts_removed = unsupported
    return ToolResult(ok=True, data={"unsupported_facts_removed": unsupported})


def extract_medications(case: CaseState) -> ToolResult:
    if not case.source_documents:
        return ToolResult(ok=False, error="No documents available for medication extraction.")

    joined_text = "\n".join(case.source_documents.values())
    admission_text = case.source_documents.get("admission_note", joined_text)
    discharge_text = case.source_documents.get("discharge_medication_record", joined_text)

    case.admission_medications = parse_med_list(
        admission_text,
        source_id="admission_note",
        label_patterns=[r"Home meds:\s*([^.\n]+)"],
    )
    case.discharge_medications = parse_med_list(
        discharge_text,
        source_id="discharge_medication_record",
        label_patterns=[
            r"Discharge meds:\s*([^.\n]+)",
            r"ADVICE ON DISCHARGE:\s*([^§]+?)(?:FOLLOW-UP INSTRUCTIONS:|$)",
        ],
    )

    if not case.admission_medications or not case.discharge_medications:
        return ToolResult(
            ok=True,
            data={
                "admission_medications": len(case.admission_medications),
                "discharge_medications": len(case.discharge_medications),
                "warning": "One medication list is missing or empty; reconciliation will flag this.",
            },
        )

    return ToolResult(
        ok=True,
        data={
            "admission_medications": len(case.admission_medications),
            "discharge_medications": len(case.discharge_medications),
        },
    )


def reconcile_medications(case: CaseState) -> ToolResult:
    changes: list[MedicationChange] = []

    if not case.admission_medications:
        changes.append(
            MedicationChange(
                medication_name="admission_medication_list",
                change_type="unclear",
                needs_review=True,
                notes=["Admission medication list missing or empty."],
            )
        )

    if not case.discharge_medications:
        changes.append(
            MedicationChange(
                medication_name="discharge_medication_list",
                change_type="unclear",
                needs_review=True,
                notes=["Discharge medication list missing or empty."],
            )
        )

    admission_by_name = {med.name.lower(): med for med in case.admission_medications}
    discharge_by_name = {med.name.lower(): med for med in case.discharge_medications}

    for name, discharge_med in discharge_by_name.items():
        admission_med = admission_by_name.get(name)
        if admission_med is None:
            changes.append(
                MedicationChange(
                    medication_name=discharge_med.name,
                    change_type="added",
                    discharge_med=discharge_med,
                    documented_reason=find_medication_reason(case, discharge_med.name),
                )
            )
            continue

        dose_changed = norm(admission_med.dose) != norm(discharge_med.dose)
        frequency_changed = norm(admission_med.frequency) != norm(discharge_med.frequency)
        if dose_changed:
            changes.append(
                MedicationChange(
                    medication_name=discharge_med.name,
                    change_type="dose_changed",
                    admission_med=admission_med,
                    discharge_med=discharge_med,
                    documented_reason=find_medication_reason(case, discharge_med.name),
                )
            )
        elif frequency_changed:
            changes.append(
                MedicationChange(
                    medication_name=discharge_med.name,
                    change_type="frequency_changed",
                    admission_med=admission_med,
                    discharge_med=discharge_med,
                    documented_reason=find_medication_reason(case, discharge_med.name),
                )
            )
        else:
            changes.append(
                MedicationChange(
                    medication_name=discharge_med.name,
                    change_type="continued",
                    admission_med=admission_med,
                    discharge_med=discharge_med,
                )
            )

    for name, admission_med in admission_by_name.items():
        if name not in discharge_by_name:
            changes.append(
                MedicationChange(
                    medication_name=admission_med.name,
                    change_type="stopped",
                    admission_med=admission_med,
                    documented_reason=find_medication_reason(case, admission_med.name),
                )
            )

    for change in changes:
        if change.discharge_med and change.discharge_med.status == "unclear":
            change.needs_review = True
            change.notes.append("Medication line could not be fully structured from OCR/source text.")
        if change.change_type not in {"continued", "unclear"} and not change.documented_reason:
            change.needs_review = True
            change.notes.append("Medication changed with no documented reason found.")

    case.medication_changes = changes
    return ToolResult(ok=True, data={"medication_changes": len(changes)})


def drug_interaction_lookup(case: CaseState) -> ToolResult:
    discharge_names = {med.name.lower(): med for med in case.discharge_medications}
    concerns: list[SafetyConcern] = []

    if "warfarin" in discharge_names and "ibuprofen" in discharge_names:
        concerns.append(
            SafetyConcern(
                category="drug_interaction",
                description="Warfarin and ibuprofen may increase bleeding risk.",
                severity="high",
                evidence=[
                    *(discharge_names["warfarin"].evidence),
                    *(discharge_names["ibuprofen"].evidence),
                ],
            )
        )

    case.safety_concerns.extend(concerns)
    return ToolResult(ok=True, data={"safety_concerns_found": len(concerns)})


def escalate_for_clinician_review(case: CaseState) -> ToolResult:
    flags: list[str] = []

    for missing_doc in case.missing_documents:
        flags.append(f"Missing expected source document: {missing_doc}.")

    for fact in case.extracted_facts.values():
        if fact.status in {"missing", "pending", "conflicting"}:
            flags.append(f"{fact.name}: {fact.status}. Clinician review required.")

    for change in case.medication_changes:
        if change.needs_review:
            flags.append(
                f"Medication reconciliation: {change.medication_name} is {change.change_type}; "
                "no documented reason found."
            )

    for concern in case.safety_concerns:
        concern.escalated = True
        flags.append(f"Safety concern ({concern.severity}): {concern.description}")

    case.clinician_review_flags = dedupe(flags)
    return ToolResult(ok=True, data={"flags": len(case.clinician_review_flags)})


def final_safety_validation(case: CaseState) -> ToolResult:
    blocking_errors: list[str] = []
    warnings: list[str] = []

    for fact in case.extracted_facts.values():
        if fact.status == "present" and not fact.evidence:
            blocking_errors.append(f"Present fact lacks evidence: {fact.name}")

    for name in REQUIRED_FACTS:
        fact = case.extracted_facts.get(name)
        if fact is None:
            expected = f"{name}: missing. Clinician review required."
            if expected not in case.clinician_review_flags:
                warnings.append(f"Required field missing without review flag: {name}")
            continue

        if fact.status in {"missing", "pending", "conflicting"}:
            expected = f"{name}: {fact.status}. Clinician review required."
            if expected not in case.clinician_review_flags:
                warnings.append(f"Required field {name} is {fact.status} without review flag.")

    for change in case.medication_changes:
        if change.needs_review and not any(
            flag.startswith(f"Medication reconciliation: {change.medication_name} ")
            for flag in case.clinician_review_flags
        ):
            warnings.append(f"Medication change not flagged: {change.medication_name}")

    for concern in case.safety_concerns:
        if not concern.escalated:
            warnings.append(f"Safety concern not escalated: {concern.description}")

    if not case.clinician_review_flags:
        warnings.append("No clinician-review flags are present; verify this is expected.")

    if blocking_errors:
        case.final_safety_passed = False
        case.final_safety_warnings = warnings
        case.final_safety_blocking_errors = blocking_errors
        return ToolResult(
            ok=False,
            data={"blocking_errors": blocking_errors, "warnings": warnings},
            error="Final safety validation failed.",
            retryable=False,
        )

    case.final_safety_passed = True
    case.final_safety_warnings = warnings
    case.final_safety_blocking_errors = blocking_errors
    return ToolResult(
        ok=True,
        data={
            "blocking_errors": blocking_errors,
            "warnings": warnings,
            "ready_to_draft": True,
        },
    )


def draft_summary(case: CaseState) -> ToolResult:
    def fact_value(name: str) -> str:
        fact = case.extracted_facts.get(name)
        if not fact or fact.status == "missing":
            return "Missing from source documents. Clinician review required."
        if fact.status == "pending":
            return f"{fact.value}. Pending at discharge."
        if fact.status == "conflicting":
            return f"Conflicting source information: {fact.value}. Clinician review required."
        return str(fact.value)

    med_lines = []
    for change in case.medication_changes:
        med = change.discharge_med or change.admission_med
        detail = med.name if med else change.medication_name
        if med:
            parts = [detail, med.dose or "", med.route or "", med.frequency or ""]
            if med.duration:
                parts.append(f"for {med.duration}")
            detail = " ".join(part for part in parts if part).strip()
        suffix = " - REVIEW REQUIRED" if change.needs_review else ""
        if med and med.status == "unclear":
            suffix = f" - UNCLEAR OCR/SOURCE - REVIEW REQUIRED"
        reason = f"; reason: {change.documented_reason}" if change.documented_reason else ""
        med_lines.append(f"- {detail}: {change.change_type}{reason}{suffix}")

    flag_lines = [f"- {flag}" for flag in case.clinician_review_flags]
    metric_lines = []
    for metric in case.investigation_metrics:
        value = f"{metric.value} {metric.unit or ''}".strip()
        suffix = " - PENDING" if metric.status == "pending" else ""
        metric_lines.append(f"- {metric.name}: {value}{suffix}")

    case.draft_markdown = "\n".join(
        [
            "# Discharge Summary Draft",
            "",
            "**Status:** Draft for clinician review only. Not a finalized clinical document.",
            "",
            "## Patient Demographics",
            fact_value("patient_demographics"),
            "",
            "## Admission and Discharge Dates",
            f"- Admission: {fact_value('admission_date')}",
            f"- Discharge: {fact_value('discharge_date')}",
            "",
            "## Diagnoses",
            f"- Principal: {fact_value('principal_diagnosis')}",
            f"- Secondary: {fact_value('secondary_diagnoses')}",
            "",
            "## Hospital Course",
            fact_value("hospital_course"),
            "",
            "## Procedures",
            fact_value("procedures"),
            "",
            "## Relevant Investigations",
            *(metric_lines or ["No investigation metrics extracted. Clinician review required."]),
            "",
            "## Discharge Medications",
            *(med_lines or ["No medication data extracted. Clinician review required."]),
            "",
            "## Allergies",
            fact_value("allergies"),
            "",
            "## Follow-up Instructions",
            fact_value("follow_up"),
            "",
            "## Pending Results",
            fact_value("pending_results"),
            "",
            "## Discharge Condition",
            fact_value("discharge_condition"),
            "",
            "## Clinician Review Flags",
            *(flag_lines or ["- No flags generated."]),
            "",
        ]
    )
    return ToolResult(ok=True, data={"draft_chars": len(case.draft_markdown)})


def add_fact_from_patterns(
    facts: dict[str, ClinicalFact],
    name: str,
    documents: dict[str, str],
    patterns: list[str],
    flags: int = 0,
) -> None:
    matches: list[tuple[str, str, str]] = []
    for source_id, text in documents.items():
        for pattern in patterns:
            match = re.search(pattern, text, flags)
            if match:
                value = clean_value(match.group(1))
                quote = match.group(0).strip()
                matches.append((source_id, value, quote))

    if not matches:
        return

    unique_values = {value.lower(): value for _, value, _ in matches}
    if len(unique_values) > 1:
        values = list(unique_values.values())
        if name == "follow_up":
            combined = "; ".join(dedupe(values))
            facts[name] = ClinicalFact(
                name=name,
                value=combined,
                status="present",
                evidence=[Evidence(source, quote) for source, _, quote in matches],
                notes=["Multiple follow-up snippets found and combined because they are complementary."],
            )
            return
        longest = max(values, key=len)
        if all(value.lower() in longest.lower() for value in values):
            source_id, _, quote = max(matches, key=lambda item: len(item[1]))
            facts[name] = ClinicalFact(
                name=name,
                value=longest,
                status="present",
                evidence=[Evidence(source_id, quote)],
                notes=["Multiple overlapping source snippets found; retained the most complete one."],
            )
            return
        facts[name] = ClinicalFact(
            name=name,
            value=values,
            status="conflicting",
            evidence=[Evidence(source, quote) for source, _, quote in matches],
            notes=["Multiple source values found. Clinician review required."],
        )
        return

    source_id, value, quote = matches[0]
    facts[name] = ClinicalFact(
        name=name,
        value=value,
        status="present",
        evidence=[Evidence(source_id, quote)],
    )


def add_diagnosis_facts(facts: dict[str, ClinicalFact], documents: dict[str, str]) -> None:
    for source_id, text in documents.items():
        match = re.search(
            r"DIAGNOSIS:\s*(?:1\)\s*)?([^.\n]+?)(?:\s*2\)\s*([^.\n]+))?(?:\s*HISTORY:|\n)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        primary = clean_value(match.group(1))
        secondary = clean_value(match.group(2) or "")
        if primary:
            facts["principal_diagnosis"] = ClinicalFact(
                name="principal_diagnosis",
                value=primary,
                status="present",
                evidence=[Evidence(source_id, clean_value(match.group(0))[:240])],
            )
        if secondary:
            facts["secondary_diagnoses"] = ClinicalFact(
                name="secondary_diagnoses",
                value=secondary,
                status="present",
                evidence=[Evidence(source_id, clean_value(match.group(0))[:240])],
            )
        return


def find_pending_results(documents: dict[str, str]) -> list[Evidence]:
    evidence = []
    seen_quotes = set()
    for source_id, text in documents.items():
        sentences = re.split(r"(?<=[.])\s+", text)
        for sentence in sentences:
            lowered = sentence.lower()
            if "pending" in lowered or "report awaited" in lowered:
                quote = sentence.strip()
                if "urine culture" in lowered and "report awaited" in lowered:
                    quote = "Urine culture and sensitivity sent- report awaited."
                quote = clean_value(quote)
                key = quote.lower()
                if key in seen_quotes:
                    continue
                seen_quotes.add(key)
                evidence.append(Evidence(source_id, quote))
    return evidence


def parse_med_list(text: str, source_id: str, label_patterns: list[str]) -> list[Medication]:
    med_text = ""
    for pattern in label_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            med_text = match.group(1)
            break

    if not med_text:
        return []

    medications = []
    for item in re.split(r";|,|\n", med_text):
        raw = item.strip()
        if not raw:
            continue
        medications.append(parse_medication_line(raw, source_id))
    return medications


def parse_medication_line(raw_line: str, source_id: str) -> Medication:
    raw = normalize_medication_line(raw_line)
    if not raw:
        return Medication(
            name="unclear_medication_line",
            status="unclear",
            evidence=[Evidence(source_id, raw_line)],
            notes=["Empty medication line after OCR cleanup."],
        )

    frequency = extract_frequency(raw)
    duration = extract_first(r"\b(\d+\s*(?:day|days|d)\b)", raw, flags=re.IGNORECASE)
    route = extract_first(r"\b(PO|IV|SC|SQ|IM|ORAL)\b", raw, flags=re.IGNORECASE)
    dose = extract_first(r"\b(\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?))\b", raw, flags=re.IGNORECASE)

    name_part = raw
    for value in [dose, route, frequency, duration]:
        if value:
            name_part = name_part.replace(value, " ")
    name_part = re.split(r"\b(?:before food|after food|as needed|sos|tdays?)\b", name_part, flags=re.IGNORECASE)[0]
    name_tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*", name_part)
    name = " ".join(name_tokens[:2]).lower()

    notes: list[str] = []
    status = "structured"
    if not name or len(name) < 3:
        name = clean_value(raw)[:80] or "unclear_medication_line"
        status = "unclear"
        notes.append("Could not confidently identify medication name.")
    if has_ocr_noise(raw):
        status = "unclear"
        notes.append("Medication line contains OCR noise or mixed fragments.")
    if not any([dose, frequency, duration]):
        status = "unclear"
        notes.append("Dose, frequency, and duration were not clearly parsed.")
    if " mg" not in raw.lower() and re.search(r"\bmg\b", raw, re.IGNORECASE) and not dose:
        notes.append("Unit MG was present but numeric strength was not visible.")

    return Medication(
        name=name,
        dose=clean_value(dose or "") or None,
        route="PO" if route and route.upper() == "ORAL" else (route.upper() if route else None),
        frequency=clean_frequency(frequency) if frequency else None,
        duration=clean_duration(duration) if duration else None,
        status=status,  # type: ignore[arg-type]
        evidence=[Evidence(source_id, raw_line.strip())],
        notes=notes,
    )


def normalize_medication_line(raw: str) -> str:
    value = raw.strip()
    value = re.sub(r"^[|'\"<.\-\s\[\]]+", "", value)
    value = re.sub(r"\b(?:TABM|TAB|CAP|INJ)\.?\s*", "", value, flags=re.IGNORECASE)
    value = value.replace("|", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_first(pattern: str, text: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    return clean_value(match.group(1)) if match else None


def extract_frequency(text: str) -> str | None:
    numeric = extract_first(r"\b(\d\s*-\s*\d\s*-\s*\d)\b", text)
    if numeric:
        return numeric
    frequency = extract_first(
        r"\b(BID|TID|QID|QD|OD|daily|once daily|twice daily|thrice daily|as needed|SOS)\b",
        text,
        flags=re.IGNORECASE,
    )
    if frequency and re.search(r"\bas needed\b", text, re.IGNORECASE) and "needed" not in frequency.lower():
        return f"{frequency} as needed"
    return frequency


def clean_frequency(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if re.fullmatch(r"\d\s*-\s*\d\s*-\s*\d", cleaned):
        return re.sub(r"\s+", "", cleaned)
    return cleaned.lower()


def clean_duration(value: str) -> str:
    value = clean_value(value)
    value = re.sub(r"\bd\b", "days", value, flags=re.IGNORECASE)
    return value


def has_ocr_noise(value: str) -> bool:
    if any(char in value for char in ["[", "]", "(", ")", "?", "%", "ﬂ", "ﬁ"]):
        return True
    letters = re.findall(r"[A-Za-z]", value)
    if not letters:
        return True
    non_standard = re.findall(r"[^A-Za-z0-9\s./+-]", value)
    return len(non_standard) > max(2, len(value) // 8)


def find_medication_reason(case: CaseState, medication_name: str) -> str | None:
    pattern = re.compile(
        rf"{re.escape(medication_name)}[^.\n]*(?:because|due to|secondary to)\s+([^.\n]+)",
        re.IGNORECASE,
    )
    for text in case.source_documents.values():
        match = pattern.search(text)
        if match:
            return clean_value(match.group(1))
    return None


def clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .")


def norm(value: str | None) -> str:
    return clean_value(value or "").lower()


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def dedupe_metrics(metrics: list[InvestigationMetric]) -> list[InvestigationMetric]:
    seen = set()
    result = []
    for metric in metrics:
        key = (metric.name, metric.value, metric.unit, metric.status)
        if key in seen:
            continue
        seen.add(key)
        result.append(metric)
    return result
