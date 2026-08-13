"""Deterministic safety boundary for the citizen-facing conversation voice."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol


ToneCategory = Literal["political", "medical", "legal", "financial", "abuse"]


@dataclass(frozen=True, slots=True)
class ToneDecision:
    allowed: bool
    category: ToneCategory | None = None
    reason_code: str = "allowed"


class ToneGovernor(Protocol):
    def review(self, text: str) -> ToneDecision: ...


class DeterministicToneGovernor:
    """Reject unsafe advice requests before the casual handler can answer.

    This is intentionally a small, auditable lexical boundary. It is not a
    general moderation claim and does not rewrite citizen complaint facts. A
    grounded scheme request and a civic filing continue to their constrained
    handlers; the policy is applied to casual, advice-seeking conversation.
    """

    _patterns: tuple[tuple[ToneCategory, str, tuple[str, ...]], ...] = (
        (
            "political",
            "political_topic",
            (
                r"\belection\w*\b",
                r"\bpolitic\w*\b",
                r"\bpolitician\w*\b",
                r"\bparty\b",
                r"\bvote\b",
                r"\bmla\b",
                r"\bmp\b",
                r"\bminister\w*\b",
                "चुनाव",
                "राजनीति",
                "नेता",
                "विधायक",
                "सांसद",
                "मंत्री",
            ),
        ),
        (
            "medical",
            "medical_advice",
            (
                r"\bmedical advice\b",
                r"\bdiagnos\w*\b",
                r"\btreatment\b",
                r"\bmedicine\b",
                r"\bdoctor\b",
                r"\bsymptom\w*\b",
                "चिकित्सा सलाह",
                "इलाज",
                "दवा",
                "डॉक्टर",
                "लक्षण",
            ),
        ),
        (
            "legal",
            "legal_advice",
            (
                r"\blegal advice\b",
                r"\blawyer\b",
                r"\bcourt\b",
                r"\blawsuit\b",
                r"\bfir\b",
                r"\bsection\b",
                "कानूनी सलाह",
                "वकील",
                "अदालत",
                "मुकदमा",
                "एफआईआर",
                "धारा",
            ),
        ),
        (
            "financial",
            "financial_advice",
            (
                r"\bfinancial advice\b",
                r"\binvest\w*\b",
                r"\bloan\b",
                r"\binsurance\b",
                r"\btax\b",
                r"\bstock\w*\b",
                r"\bcrypto\w*\b",
                "निवेश",
                "कर्ज",
                "बीमा",
                "टैक्स",
                "शेयर",
            ),
        ),
        (
            "abuse",
            "threatening_or_abusive_language",
            (
                r"\bkill\s+(?:him|her|them|you)\b",
                r"\b(?:i|we)\s+will\s+(?:hurt|attack|kill)\b",
                r"\bmaar\s+d(?:u|e)nga\b",
                "मार दूंगा",
                "जान से मार",
            ),
        ),
    )

    def review(self, text: str) -> ToneDecision:
        normalized = text.strip().casefold()
        if not normalized:
            return ToneDecision(allowed=True)
        for category, reason_code, patterns in self._patterns:
            if any(re.search(pattern, normalized) for pattern in patterns):
                return ToneDecision(
                    allowed=False,
                    category=category,
                    reason_code=reason_code,
                )
        return ToneDecision(allowed=True)


def refusal_text(category: ToneCategory) -> str:
    messages: dict[ToneCategory, str] = {
        "political": "Main rajneeti ya chunav par salah nahi de sakta. Main civic shikayat ya uska status dikhane mein madad kar sakta hoon.",
        "medical": "Main medical salah nahi de sakta. Main civic problem ki shikayat ya status mein madad kar sakta hoon.",
        "legal": "Main legal salah nahi de sakta. Main civic shikayat ko saaf tareeke se darj karne mein madad kar sakta hoon.",
        "financial": "Main financial salah nahi de sakta. Main verified sarkari yojana ki jankari ya civic shikayat mein madad kar sakta hoon.",
        "abuse": "Main shaant aur sammanjanak bhasha mein madad karunga. Aap civic problem ko seedhe shabdon mein batayein.",
    }
    return messages[category]
