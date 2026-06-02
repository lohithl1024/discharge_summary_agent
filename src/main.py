from __future__ import annotations

import argparse
from pathlib import Path

from agent import DischargeSummaryAgent
from validation_report import write_validation_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the discharge summary agent.")
    parser.add_argument("--patient-id", default=None)
    parser.add_argument("--pdf", action="append", default=[], help="Path to a patient source-note PDF.")
    args = parser.parse_args()

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    patient_ids = [args.patient_id or "real_patient"] if args.pdf else ["mock_patient_001", "mock_patient_missing"]

    for patient_id in patient_ids:
        agent = DischargeSummaryAgent()
        case = agent.run(patient_id=patient_id, source_paths=args.pdf)

        summary_path = output_dir / f"{patient_id}_summary.md"
        trace_path = output_dir / f"{patient_id}_trace.json"
        validation_path = output_dir / f"{patient_id}_validation_report.json"

        summary_path.write_text(case.draft_markdown or "No draft generated.\n", encoding="utf-8")
        agent.trace.write_json(trace_path)
        write_validation_report(case, validation_path)

        print(f"Wrote {summary_path}")
        print(f"Wrote {trace_path}")
        print(f"Wrote {validation_path}")


if __name__ == "__main__":
    main()
