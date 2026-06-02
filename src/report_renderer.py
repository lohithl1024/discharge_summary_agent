from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from pathlib import Path


SECTION_ORDER = [
    "Patient Demographics",
    "Admission and Discharge Dates",
    "Diagnoses",
    "Hospital Course",
    "Procedures",
    "Relevant Investigations",
    "Discharge Medications",
    "Allergies",
    "Follow-up Instructions",
    "Pending Results",
    "Discharge Condition",
    "Clinician Review Flags",
]


def render_report(markdown_path: Path, html_path: Path, pdf_path: Path | None = None) -> None:
    markdown = markdown_path.read_text(encoding="utf-8")
    title, status, sections = parse_summary(markdown)
    validation = load_validation_report(markdown_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_html(title, status, sections, validation), encoding="utf-8")

    if pdf_path is not None:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            convert_html_to_pdf(html_path, pdf_path)
        except RuntimeError as exc:
            print(f"PDF conversion skipped: {exc}")


def parse_summary(markdown: str) -> tuple[str, str, dict[str, str]]:
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Discharge Summary Draft"

    status_match = re.search(r"\*\*Status:\*\*\s*(.+)", markdown)
    status = status_match.group(1).strip() if status_match else "Draft for clinician review only."

    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+)$", markdown, re.MULTILINE))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        sections[heading] = body

    return title, status, sections


def load_validation_report(markdown_path: Path) -> dict | None:
    candidate = markdown_path.with_name(markdown_path.name.replace("_summary.md", "_validation_report.json"))
    if not candidate.exists():
        return None
    return json.loads(candidate.read_text(encoding="utf-8"))


def build_html(title: str, status: str, sections: dict[str, str], validation: dict | None) -> str:
    patient_name = extract_first_value(sections.get("Patient Demographics", "Not available"))
    diagnosis = extract_diagnosis(sections.get("Diagnoses", "Not available"))
    condition = extract_first_value(sections.get("Discharge Condition", "Not available"))
    review_flags = parse_list_items(sections.get("Clinician Review Flags", ""))
    review_count = len(review_flags)
    final_gate = validation.get("final_safety_gate", {}) if validation else {}
    safety_status = "Passed" if final_gate.get("passed") else "Needs review"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    @page {{ size: A4; margin: 14mm 14mm; }}

    :root {{
      --ink: #162033;
      --muted: #667085;
      --line: #cfd8e3;
      --soft: #f6f8fb;
      --accent: #155e75;
      --accent-dark: #164e63;
      --warning: #9a3412;
      --warning-bg: #fff7ed;
      --missing-bg: #fef2f2;
      --missing: #991b1b;
      --green-bg: #ecfdf5;
      --green: #047857;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      color: var(--ink);
      font: 11.5pt/1.38 "Times New Roman", Times, Georgia, serif;
      background: #ffffff;
    }}

    .page {{
      max-width: 1040px;
      margin: 0 auto;
      padding: 18px;
    }}

    .letterhead {{
      border-bottom: 4px solid var(--accent);
      padding-bottom: 12px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 20px;
      align-items: end;
    }}

    .brand {{
      font-size: 18pt;
      font-weight: 800;
      letter-spacing: 0;
      color: #000000;
    }}

    .subtitle {{
      color: var(--muted);
      margin-top: 4px;
      font-size: 10.5pt;
    }}

    .draft-badge {{
      border: 1px solid var(--warning);
      background: var(--warning-bg);
      color: var(--warning);
      padding: 6px 10px;
      font-weight: 700;
      text-align: center;
      min-width: 160px;
      font-size: 10.5pt;
    }}

    .patient-band {{
      margin: 14px 0;
      border: 1px solid var(--line);
      display: grid;
      grid-template-columns: 1.3fr 1fr;
      gap: 0;
    }}

    .patient-band > div {{
      padding: 12px;
      border-right: 1px solid var(--line);
    }}

    .patient-band > div:last-child {{
      border-right: 0;
    }}

    .patient-name {{
      font-size: 16pt;
      font-weight: 800;
      color: #000000;
    }}

    .micro {{
      color: var(--muted);
      font-size: 9.5pt;
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 3px;
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }}

    .metric {{
      background: var(--soft);
      display: grid;
      border: 1px solid var(--line);
      padding: 8px;
      min-height: 58px;
    }}

    .metric-label {{
      color: var(--muted);
      font-size: 9pt;
      text-transform: uppercase;
      font-weight: 800;
    }}

    .metric-value {{
      margin-top: 3px;
      font-weight: 700;
    }}

    .notice {{
      border-left: 4px solid var(--warning);
      background: var(--warning-bg);
      padding: 9px 11px;
      margin: 12px 0;
      color: #55270b;
    }}

    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }}

    .section {{
      border: 1px solid var(--line);
      margin: 10px 0;
      break-inside: avoid;
    }}

    .section h2 {{
      margin: 0;
      padding: 8px 10px;
      background: #eaf5f8;
      color: #000000;
      font-size: 11.5pt;
      text-transform: uppercase;
      letter-spacing: .02em;
      border-bottom: 1px solid var(--line);
    }}

    .section-body {{ padding: 10px; }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 10pt;
    }}

    th {{
      text-align: left;
      background: #f1f5f9;
      color: #334155;
      font-weight: 700;
      border: 1px solid var(--line);
      padding: 6px;
    }}

    td {{
      border: 1px solid var(--line);
      padding: 6px;
      vertical-align: top;
    }}

    .status {{
      display: inline-block;
      padding: 2px 6px;
      font-weight: 700;
      font-size: 9pt;
      border-radius: 999px;
    }}

    .status-ok {{ background: var(--green-bg); color: var(--green); }}
    .status-review {{ background: var(--warning-bg); color: var(--warning); }}
    .status-missing {{ background: var(--missing-bg); color: var(--missing); }}

    .pill {{
      display: inline-block;
      padding: 2px 6px;
      border: 1px solid var(--line);
      background: #fff;
      margin: 2px 3px 2px 0;
      font-size: 9pt;
    }}

    .flags li {{ margin-bottom: 6px; }}
    .small {{ color: var(--muted); font-size: 9.5pt; }}
    .avoid-break {{ break-inside: avoid; }}

    p {{ margin: 0 0 7px; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 4px 0; }}

    .missing {{
      background: var(--missing-bg);
      color: var(--missing);
      padding: 1px 4px;
      font-weight: 700;
    }}

    .review {{
      background: var(--warning-bg);
      color: var(--warning);
      padding: 1px 4px;
      font-weight: 700;
    }}

    .pending {{
      background: #fefce8;
      color: #854d0e;
      padding: 1px 4px;
      font-weight: 700;
    }}

    .footer {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 9.5pt;
      border-top: 1px solid var(--line);
      padding-top: 8px;
    }}

    @media print {{ .page {{ padding: 0; }} }}
  </style>
</head>
<body>
  <main class="page">
    <header class="letterhead">
      <div>
        <div class="brand">Discharge Summary Draft</div>
        <div class="subtitle">Patient-friendly hospital discharge packet · Source-grounded AI draft</div>
      </div>
      <div class="draft-badge">DRAFT ONLY</div>
    </header>

    <section class="patient-band">
      <div>
        <div class="micro">Patient</div>
        <div class="patient-name">{html.escape(patient_name)}</div>
        <div class="small">This field is marked missing if not clearly present in the source documents.</div>
      </div>
      <div>
        <div class="micro">Primary Diagnosis</div>
        <strong>{html.escape(diagnosis)}</strong>
      </div>
    </section>

    <section class="summary-grid">
      {render_metric("Admission", extract_admission(sections.get("Admission and Discharge Dates", "")))}
      {render_metric("Discharge", extract_discharge(sections.get("Admission and Discharge Dates", "")))}
      {render_metric("Condition", condition)}
      {render_metric("Safety Gate", safety_status)}
    </section>

    <div class="notice">{html.escape(status)} This report is designed to be easy to read, but it still requires clinician review before use.</div>

    {render_section("Diagnoses", sections.get("Diagnoses", ""))}
    {render_section("Hospital Course", sections.get("Hospital Course", ""))}
    {render_investigation_table(sections.get("Relevant Investigations", ""))}
    {render_medication_table(validation, sections.get("Discharge Medications", ""))}

    <div class="two-col">
      {render_section("Follow-up Instructions", sections.get("Follow-up Instructions", ""))}
      {render_section("Pending Results", sections.get("Pending Results", ""))}
    </div>

    <div class="two-col">
      {render_section("Procedures", sections.get("Procedures", ""))}
      {render_section("Allergies", sections.get("Allergies", ""))}
    </div>

    {render_review_flags(review_flags, review_count)}

    <footer class="footer">
      Generated from source documents by the discharge-summary agent. Missing, pending, unclear, and medication-reconciliation items are intentionally flagged instead of guessed.
    </footer>
  </main>
</body>
</html>
"""


def render_metric(label: str, value: str) -> str:
    return (
        '<div class="metric">'
        f'<div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{html.escape(value or "Not available")}</div>'
        "</div>"
    )


def render_section(heading: str, body: str) -> str:
    return (
        '<section class="section">'
        f"<h2>{html.escape(heading)}</h2>"
        f'<div class="section-body">{markdown_fragment_to_html(body)}</div>'
        "</section>"
    )


def render_investigation_table(body: str) -> str:
    items = parse_list_items(body)
    if not items:
        return render_section("Relevant Investigations", body)

    rows = []
    for item in items:
        name, value = split_label_value(item)
        status = "Pending" if "PENDING" in item.upper() else "Available"
        status_class = "status-review" if status == "Pending" else "status-ok"
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{inline_markup(value)}</td>"
            f'<td><span class="status {status_class}">{status}</span></td>'
            "</tr>"
        )

    return (
        '<section class="section avoid-break">'
        "<h2>Relevant Investigations</h2>"
        '<div class="section-body">'
        "<table>"
        "<thead><tr><th>Investigation</th><th>Result / Finding</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div></section>"
    )


def render_medication_table(validation: dict | None, fallback_body: str) -> str:
    medications = []
    if validation:
        medications = validation.get("medication_extraction", {}).get("discharge_medications", [])

    if not medications:
        return render_section("Discharge Medications", fallback_body)

    rows = []
    for medication in medications:
        status = medication.get("status") or "structured"
        notes = medication.get("notes") or []
        status_class = "status-review" if status == "unclear" else "status-ok"
        note_text = "; ".join(notes) if notes else "Parsed from source text"
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(display_value(medication.get('name')))}</strong></td>"
            f"<td>{html.escape(display_value(medication.get('dose')))}</td>"
            f"<td>{html.escape(display_value(medication.get('frequency')))}</td>"
            f"<td>{html.escape(display_value(medication.get('duration')))}</td>"
            f'<td><span class="status {status_class}">{html.escape(status.upper())}</span></td>'
            f"<td>{html.escape(note_text)}</td>"
            "</tr>"
        )

    return (
        '<section class="section avoid-break">'
        "<h2>Discharge Medications</h2>"
        '<div class="section-body">'
        '<p class="small">Medication details are separated into fields. Unclear OCR/source items are intentionally highlighted for clinician reconciliation.</p>'
        "<table>"
        "<thead><tr><th>Medicine</th><th>Dose</th><th>Frequency</th><th>Duration</th><th>Status</th><th>Review Note</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div></section>"
    )


def render_review_flags(flags: list[str], review_count: int) -> str:
    if not flags:
        return (
            '<section class="section">'
            "<h2>Clinician Review Flags</h2>"
            '<div class="section-body"><p>No review flags generated.</p></div>'
            "</section>"
        )
    items = "".join(f"<li>{inline_markup(flag)}</li>" for flag in flags)
    return (
        '<section class="section">'
        f"<h2>Clinician Review Flags ({review_count})</h2>"
        f'<div class="section-body"><ul class="flags">{items}</ul></div>'
        "</section>"
    )


def markdown_fragment_to_html(text: str) -> str:
    lines = text.splitlines()
    html_parts: list[str] = []
    list_items: list[str] = []

    def flush_list() -> None:
        if list_items:
            html_parts.append("<ul>" + "".join(list_items) + "</ul>")
            list_items.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_list()
            continue
        if stripped.startswith("- "):
            list_items.append(f"<li>{inline_markup(stripped[2:])}</li>")
        else:
            flush_list()
            html_parts.append(f"<p>{inline_markup(stripped)}</p>")

    flush_list()
    return "".join(html_parts) or "<p>Not available.</p>"


def parse_list_items(text: str) -> list[str]:
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def split_label_value(item: str) -> tuple[str, str]:
    if ":" not in item:
        return item, ""
    name, value = item.split(":", 1)
    return name.strip().replace("_", " ").title(), value.strip()


def display_value(value) -> str:
    if value is None or value == "":
        return "Not clearly documented"
    return str(value)


def extract_admission(text: str) -> str:
    for line in text.splitlines():
        if "Admission:" in line:
            return line.split("Admission:", 1)[1].strip()
    return "Not available"


def extract_discharge(text: str) -> str:
    for line in text.splitlines():
        if "Discharge:" in line:
            return line.split("Discharge:", 1)[1].strip()
    return "Not available"


def inline_markup(text: str) -> str:
    escaped = html.escape(text)
    replacements = [
        ("Missing from source documents. Clinician review required.", "missing"),
        ("Clinician review required.", "review"),
        ("REVIEW REQUIRED", "review"),
        ("Pending at discharge.", "pending"),
        ("PENDING", "pending"),
    ]
    for phrase, klass in replacements:
        escaped_phrase = html.escape(phrase)
        escaped = escaped.replace(
            escaped_phrase,
            f'<span class="{klass}">{escaped_phrase}</span>',
        )
    return escaped


def extract_first_value(text: str) -> str:
    cleaned = re.sub(r"^- ", "", text.strip().splitlines()[0].strip()) if text.strip() else ""
    return cleaned or "Not available"


def extract_diagnosis(text: str) -> str:
    for line in text.splitlines():
        if "Principal:" in line:
            return line.split("Principal:", 1)[1].strip()
    return extract_first_value(text)


def count_review_flags(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip().startswith("- "))


def convert_html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    chrome = find_chrome()
    if chrome is not None:
        with TemporaryDirectory() as user_data_dir:
            try:
                subprocess.run(
                    [
                        str(chrome),
                        "--headless=new",
                        "--disable-gpu",
                        "--no-first-run",
                        "--no-default-browser-check",
                        f"--user-data-dir={user_data_dir}",
                        f"--print-to-pdf={pdf_path.resolve()}",
                        html_path.resolve().as_uri(),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                return
            except subprocess.CalledProcessError:
                if pdf_path.exists() and pdf_path.stat().st_size == 0:
                    pdf_path.unlink()

    try:
        completed = subprocess.run(
            ["cupsfilter", str(html_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        if pdf_path.exists() and pdf_path.stat().st_size == 0:
            pdf_path.unlink()
        raise RuntimeError(exc.stderr.decode("utf-8", errors="ignore").strip()) from exc

    pdf_path.write_bytes(completed.stdout)


def find_chrome() -> Path | None:
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a polished discharge summary report.")
    parser.add_argument("summary_md", help="Path to the generated Markdown summary.")
    parser.add_argument("--html", default=None, help="Output HTML path.")
    parser.add_argument("--pdf", default=None, help="Output PDF path.")
    args = parser.parse_args()

    summary_path = Path(args.summary_md)
    html_path = Path(args.html) if args.html else summary_path.with_suffix(".styled.html")
    pdf_path = Path(args.pdf) if args.pdf else summary_path.with_suffix(".styled.pdf")
    render_report(summary_path, html_path, pdf_path)
    print(f"Wrote {html_path}")
    print(f"Wrote {pdf_path}")


if __name__ == "__main__":
    main()
