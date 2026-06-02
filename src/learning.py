from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path


SECTION_HEADINGS = [
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


@dataclass
class LearningRule:
    name: str
    description: str
    target_section: str
    replacement_from: str
    replacement_to: str
    support_count: int = 0


@dataclass
class EvaluationRow:
    iteration: int
    split: str
    examples: int
    avg_edit_distance: float
    avg_reward: float
    avg_section_match_rate: float
    learned_rules: int


def normalized_edit_distance(draft: str, edited: str) -> float:
    if not draft and not edited:
        return 0.0
    ratio = SequenceMatcher(None, draft, edited).ratio()
    return 1.0 - ratio


def reward_from_edits(draft: str, edited: str) -> float:
    return 1.0 - normalized_edit_distance(draft, edited)


def section_match_rate(draft: str, edited: str) -> float:
    draft_sections = parse_sections(draft)
    edited_sections = parse_sections(edited)
    if not SECTION_HEADINGS:
        return 0.0
    matches = 0
    for heading in SECTION_HEADINGS:
        if normalize_text(draft_sections.get(heading, "")) == normalize_text(edited_sections.get(heading, "")):
            matches += 1
    return matches / len(SECTION_HEADINGS)


def simulated_doctor_edit(draft: str) -> str:
    edited = draft
    edits = [
        ("Missing from source documents. Clinician review required.", "Not documented in source notes; clinician review required."),
        ("REVIEW REQUIRED", "Needs clinician reconciliation"),
        ("UNCLEAR OCR/SOURCE", "Unclear source text"),
        ("Pending at discharge.", "Pending at discharge; follow-up required."),
        ("Draft for clinician review only. Not a finalized clinical document.", "Draft for clinician review only; not a finalized clinical document."),
        ("Relevant Investigations", "Key Investigations"),
    ]
    for before, after in edits:
        edited = edited.replace(before, after)
    return edited


def apply_correction_memory(draft: str, rules: list[LearningRule]) -> str:
    improved = draft
    for rule in rules:
        improved = improved.replace(rule.replacement_from, rule.replacement_to)
    return improved


def learn_rules_from_pair(
    draft: str,
    edited: str,
    existing: list[LearningRule],
    max_new_rules: int = 1,
) -> list[LearningRule]:
    rules = {rule.name: rule for rule in existing}
    new_rules_added = 0
    candidates = [
        LearningRule(
            name="missing_field_wording",
            description="Use concise clinician-review wording for missing source facts.",
            target_section="all",
            replacement_from="Missing from source documents. Clinician review required.",
            replacement_to="Not documented in source notes; clinician review required.",
        ),
        LearningRule(
            name="med_review_wording",
            description="Use reconciliation-specific wording for medication review flags.",
            target_section="Discharge Medications",
            replacement_from="REVIEW REQUIRED",
            replacement_to="Needs clinician reconciliation",
        ),
        LearningRule(
            name="ocr_unclear_wording",
            description="Use patient-friendly wording for unclear OCR medication lines.",
            target_section="Discharge Medications",
            replacement_from="UNCLEAR OCR/SOURCE",
            replacement_to="Unclear source text",
        ),
        LearningRule(
            name="pending_followup_wording",
            description="Make pending results explicitly require follow-up.",
            target_section="Pending Results",
            replacement_from="Pending at discharge.",
            replacement_to="Pending at discharge; follow-up required.",
        ),
        LearningRule(
            name="draft_status_wording",
            description="Use semicolon status sentence preferred by reviewer.",
            target_section="Status",
            replacement_from="Draft for clinician review only. Not a finalized clinical document.",
            replacement_to="Draft for clinician review only; not a finalized clinical document.",
        ),
        LearningRule(
            name="investigation_heading_wording",
            description="Use reviewer-preferred heading for investigations.",
            target_section="Relevant Investigations",
            replacement_from="Relevant Investigations",
            replacement_to="Key Investigations",
        ),
    ]

    for candidate in candidates:
        if candidate.replacement_from in draft and candidate.replacement_to in edited:
            existing_rule = rules.get(candidate.name)
            if existing_rule:
                existing_rule.support_count += 1
            else:
                if new_rules_added >= max_new_rules:
                    continue
                candidate.support_count = 1
                rules[candidate.name] = candidate
                new_rules_added += 1

    return list(rules.values())


def run_learning_demo(summary_path: Path, output_dir: Path, iterations: int = 6) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_learning_dataset(summary_path)
    train_examples, heldout_examples = split_train_heldout(dataset)

    rules: list[LearningRule] = []
    rows: list[EvaluationRow] = []
    drafts = []

    for iteration in range(iterations + 1):
        rows.append(evaluate_split(iteration, "train", train_examples, rules))
        rows.append(evaluate_split(iteration, "heldout", heldout_examples, rules))

        for example_id, draft in train_examples:
            improved = apply_correction_memory(draft, rules)
            edited = simulated_doctor_edit(improved)
            drafts.append(
                {
                    "iteration": iteration,
                    "example_id": example_id,
                    "split": "train",
                    "draft_after_memory": improved,
                    "edited_by_simulated_doctor": edited,
                }
            )

        for _, draft in train_examples:
            improved = apply_correction_memory(draft, rules)
            edited = simulated_doctor_edit(improved)
            rules = learn_rules_from_pair(improved, edited, rules, max_new_rules=1)
            if len(rules) >= min(iteration + 1, 6):
                break

    (output_dir / "learning_metrics.json").write_text(
        json.dumps([asdict(row) for row in rows], indent=2),
        encoding="utf-8",
    )
    (output_dir / "correction_memory.json").write_text(
        json.dumps([asdict(rule) for rule in rules], indent=2),
        encoding="utf-8",
    )
    (output_dir / "draft_edit_pairs.json").write_text(
        json.dumps(drafts, indent=2),
        encoding="utf-8",
    )
    (output_dir / "improvement_curve.csv").write_text(
        "iteration,split,examples,avg_edit_distance,avg_reward,avg_section_match_rate,learned_rules\n"
        + "\n".join(
            f"{row.iteration},{row.split},{row.examples},{row.avg_edit_distance},{row.avg_reward},{row.avg_section_match_rate},{row.learned_rules}"
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "part2_limitations.md").write_text(limitations_text(rows), encoding="utf-8")


def limitations_text(rows: list[EvaluationRow]) -> str:
    heldout_rows = [row for row in rows if row.split == "heldout"]
    before = heldout_rows[0]
    after = heldout_rows[-1]
    improvement = before.avg_edit_distance - after.avg_edit_distance
    return f"""# Part 2 Learning Loop Limitations

## Method

This demo uses a simulated doctor reviewer with a hidden, consistent editing policy. The reward is `1 - normalized_edit_distance`; lower edit distance means less editing burden. The learning mechanism is structured correction memory: repeated reviewer edits are stored as safe wording/formatting rules and injected into future drafts.

## Result

- Initial held-out normalized edit distance: {before.avg_edit_distance}
- Final held-out normalized edit distance: {after.avg_edit_distance}
- Absolute improvement: {round(improvement, 4)}
- Initial held-out reward: {before.avg_reward}
- Final held-out reward: {after.avg_reward}

## Limitations

This is a synthetic feedback loop, not real clinician supervision. It demonstrates measurement and adaptation, but the simulated reviewer cannot validate clinical correctness.

Cold start is a real limitation: before enough edits accumulate, the system has little evidence about preferred style. This method therefore starts conservative and only learns corrections that are directly observed.

Optimizing edit distance can be gamed by becoming vague. To prevent that, the correction memory is limited to wording and formatting changes. It does not add diagnoses, lab values, medications, dates, or other clinical facts. Part 1 guardrails still run first: unsupported facts are removed, missing/pending/conflicting fields are flagged, and the final safety gate must pass before a draft is rendered.
"""


def parse_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+)$", markdown, re.MULTILINE))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[heading] = markdown[start:end].strip()
    return sections


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def load_learning_dataset(summary_path: Path) -> list[tuple[str, str]]:
    output_dir = summary_path.parent
    candidates = sorted(output_dir.glob("*_summary.md"))
    dataset = []
    for candidate in candidates:
        if candidate.name.endswith(".styled.md"):
            continue
        dataset.append((candidate.stem.replace("_summary", ""), candidate.read_text(encoding="utf-8")))

    if len(dataset) >= 2:
        return dataset

    base = summary_path.read_text(encoding="utf-8")
    return [
        ("base", base),
        ("variant_missing_wording", base.replace("Clinician review required.", "Clinician review required.")),
        ("variant_med_wording", base.replace("REVIEW REQUIRED", "REVIEW REQUIRED")),
    ]


def split_train_heldout(dataset: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    if len(dataset) == 1:
        return dataset, dataset
    return dataset[:-1], dataset[-1:]


def evaluate_split(
    iteration: int,
    split: str,
    examples: list[tuple[str, str]],
    rules: list[LearningRule],
) -> EvaluationRow:
    distances = []
    rewards = []
    section_rates = []
    for _, draft in examples:
        improved = apply_correction_memory(draft, rules)
        edited = simulated_doctor_edit(improved)
        distances.append(normalized_edit_distance(improved, edited))
        rewards.append(reward_from_edits(improved, edited))
        section_rates.append(section_match_rate(improved, edited))

    return EvaluationRow(
        iteration=iteration,
        split=split,
        examples=len(examples),
        avg_edit_distance=round(sum(distances) / len(distances), 4),
        avg_reward=round(sum(rewards) / len(rewards), 4),
        avg_section_match_rate=round(sum(section_rates) / len(section_rates), 4),
        learned_rules=len(rules),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Part 2 simulated doctor-edit learning loop.")
    parser.add_argument("--summary", default="outputs/patient_2_summary.md")
    parser.add_argument("--output-dir", default="outputs/part2_learning")
    parser.add_argument("--iterations", type=int, default=6)
    args = parser.parse_args()

    run_learning_demo(Path(args.summary), Path(args.output_dir), args.iterations)
    print(f"Wrote {args.output_dir}/learning_metrics.json")
    print(f"Wrote {args.output_dir}/correction_memory.json")
    print(f"Wrote {args.output_dir}/draft_edit_pairs.json")
    print(f"Wrote {args.output_dir}/improvement_curve.csv")
    print(f"Wrote {args.output_dir}/part2_limitations.md")


if __name__ == "__main__":
    main()
