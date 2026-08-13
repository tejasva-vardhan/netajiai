"""Small, provider-independent evaluation helpers for bounded AI ports."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from backend.app.application.ports import AgentOrchestrator
from backend.app.contracts.ai import Intent


@dataclass(frozen=True, slots=True)
class IntentEvaluationCase:
    case_id: str
    text: str
    expected_intent: Intent


@dataclass(frozen=True, slots=True)
class IntentEvaluationReport:
    total: int
    correct: int
    accuracy: float
    confusion: dict[str, dict[str, int]]
    failures: tuple[str, ...]


def evaluate_intent(
    orchestrator: AgentOrchestrator,
    cases: Iterable[IntentEvaluationCase],
) -> IntentEvaluationReport:
    """Run a bounded intent set and return auditable aggregate metrics."""

    confusion_counts: Counter[tuple[str, str]] = Counter()
    failures: list[str] = []
    total = 0
    correct = 0
    for case in cases:
        predicted_intent = orchestrator.classify_intent(case.text).intent
        confusion_counts[(case.expected_intent, predicted_intent)] += 1
        total += 1
        if predicted_intent == case.expected_intent:
            correct += 1
        else:
            failures.append(case.case_id)

    confusion: dict[str, dict[str, int]] = defaultdict(dict)
    for (expected, predicted_label), count in sorted(confusion_counts.items()):
        confusion[expected][predicted_label] = count
    return IntentEvaluationReport(
        total=total,
        correct=correct,
        accuracy=(correct / total) if total else 0.0,
        confusion=dict(confusion),
        failures=tuple(failures),
    )
