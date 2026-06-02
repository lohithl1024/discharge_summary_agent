from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from schemas import TraceStep


class TraceRecorder:
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []

    def add(
        self,
        *,
        step: int,
        reasoning: str,
        action: str,
        inputs: dict[str, Any],
        result: dict[str, Any],
        next_decision: str,
    ) -> None:
        self.steps.append(
            TraceStep(
                step=step,
                reasoning=reasoning,
                action=action,
                inputs=inputs,
                result=result,
                next_decision=next_decision,
            )
        )

    def to_json(self) -> str:
        return json.dumps([asdict(step) for step in self.steps], indent=2)

    def write_json(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")

