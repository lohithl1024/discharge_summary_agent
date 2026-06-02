# Discharge Summary Agent

Starter design for an agentic AI system that reads patient source notes and drafts a clinically safe discharge summary for clinician review.

This repository is intentionally structured so the core agent can be tested before real patient PDFs are added.

## Goals

- Use a real planning loop, not a fixed one-shot prompt.
- Extract only source-supported facts.
- Mark missing, pending, or conflicting information clearly.
- Reconcile admission and discharge medications.
- Escalate safety concerns and undocumented changes for clinician review.
- Emit a readable trace for every agent step.
- Stop after a hard iteration cap.

## Architecture

```text
src/
  main.py              CLI entrypoint
  agent.py             Agent loop and decision policy
  schemas.py           Data models for facts, summaries, and trace steps
  tools.py             Tool interface and mock/starter tools
  pdf_ingestion.py     OCR/PDF text ingestion into page-level source chunks
  trace.py             Trace recorder
  tests/smoke_test.py  End-to-end smoke checks for safety-critical behavior
```

## Agent Loop

The agent repeatedly:

1. Inspects the current case state.
2. Decides the next action.
3. Calls a tool.
4. Records reasoning, action, inputs, result, and next decision.
5. Re-plans based on missing fields, conflicts, pending data, and safety flags.
6. Stops when a draft is complete enough for review or when `MAX_STEPS` is reached.

The generated summary is always a draft and must never be treated as a finalized clinical document.

## Efficiency and Safety Design

- PDF pages are ingested once and stored in the case state for all downstream tools.
- The planner passes compact document summaries into the trace instead of dumping every page name repeatedly.
- Source facts are validated before drafting; present facts without evidence are removed or downgraded.
- Missing, pending, conflicting, medication, and safety issues must be represented as clinician-review flags.
- A final safety-validation tool runs before `draft_summary`; drafting proceeds only if there are no blocking guardrail errors.
- Tool failures are caught by the agent wrapper, recorded in the trace, and used for re-planning or fallback reporting.

## Run

```bash
python3 src/main.py
```

Run against a real OCR/PDF packet:

```bash
python3 src/main.py --patient-id patient_2 --pdf "/path/to/patient.pdf"
```

For scanned non-OCR PDFs, install OCR support:

```bash
brew install tesseract
python3 -m pip install -r requirements.txt
```

The agent first tries embedded PDF text. If too little text is found, it falls back to page rendering plus Tesseract OCR. If OCR dependencies are missing and the PDF has no usable embedded text, the agent fails safely and reports that OCR is required.

Each run writes three review artifacts:

```text
outputs/<patient_id>_summary.md
outputs/<patient_id>_trace.json
outputs/<patient_id>_validation_report.json
```

The validation report includes missing fields, pending results, unsupported facts removed, medication extraction details, medication reconciliation changes, safety concerns, review flags, and final safety-gate status.

## Part 2: Learning From Simulated Doctor Edits

Run the stretch learning demo:

```bash
python3 src/learning.py --summary outputs/patient_2_summary.md --output-dir outputs/part2_learning --iterations 6
```

This creates:

```text
outputs/part2_learning/learning_metrics.json
outputs/part2_learning/correction_memory.json
outputs/part2_learning/draft_edit_pairs.json
outputs/part2_learning/improvement_curve.csv
outputs/part2_learning/part2_limitations.md
```

The simulated doctor applies a hidden editing policy. The reward is `1 - normalized_edit_distance`, so lower edit burden produces higher reward. The learning mechanism is a structured correction memory that learns wording and formatting preferences only; it does not add or change clinical facts, so the Part 1 no-fabrication guardrails remain intact.

## Next Implementation Steps

1. Add `pdf_ingestion.py` with text extraction and OCR fallback.
2. Add an LLM-backed extraction tool that returns structured facts with evidence.
3. Add stronger conflict detection across notes.
4. Add real medication parsing and reconciliation.
5. Add output writers for `outputs/<patient>_summary.md` and `outputs/<patient>_trace.json`.
6. Add demo patients and run the agent on at least two cases.
