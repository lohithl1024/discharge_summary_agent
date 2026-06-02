# Part 2 Learning Loop Limitations

## Method

This demo uses a simulated doctor reviewer with a hidden, consistent editing policy. The reward is `1 - normalized_edit_distance`; lower edit distance means less editing burden. The learning mechanism is structured correction memory: repeated reviewer edits are stored as safe wording/formatting rules and injected into future drafts.

## Result

- Initial held-out normalized edit distance: 0.1043
- Final held-out normalized edit distance: 0.0274
- Absolute improvement: 0.0769
- Initial held-out reward: 0.8957
- Final held-out reward: 0.9726

## Limitations

This is a synthetic feedback loop, not real clinician supervision. It demonstrates measurement and adaptation, but the simulated reviewer cannot validate clinical correctness.

Cold start is a real limitation: before enough edits accumulate, the system has little evidence about preferred style. This method therefore starts conservative and only learns corrections that are directly observed.

Optimizing edit distance can be gamed by becoming vague. To prevent that, the correction memory is limited to wording and formatting changes. It does not add diagnoses, lab values, medications, dates, or other clinical facts. Part 1 guardrails still run first: unsupported facts are removed, missing/pending/conflicting fields are flagged, and the final safety gate must pass before a draft is rendered.
