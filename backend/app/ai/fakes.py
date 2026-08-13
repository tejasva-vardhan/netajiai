"""Deterministic AI fake for tests and local contract development."""

from __future__ import annotations

from backend.app.contracts.ai import ComplaintExtraction, Intent, IntentClassification
from backend.app.contracts.conversation import ConversationContext


class FakeAgentOrchestrator:
    """A fixture adapter; never enabled for production by configuration."""

    def classify_intent(
        self, text: str, *, context: ConversationContext | None = None
    ) -> IntentClassification:
        normalized = text.casefold()
        intent: Intent
        reason: str
        if context is not None and normalized.strip() in {
            "haan",
            "yes",
            "okay",
            "ok",
            "continue",
            "theek hai",
            "ठीक है",
        }:
            intent = "continuation"
            reason = "continuation_signal"
        elif any(
            term in normalized
            for term in ("status", "track", "complaint id", "स्थिति", "शिकायत की स्थिति")
        ):
            intent = "status"
            reason = "contains_status_signal"
        elif any(
            term in normalized
            for term in ("scheme", "yojana", "eligibility", "योजना", "पात्रता")
        ):
            intent = "scheme"
            reason = "contains_scheme_signal"
        elif any(
            term in normalized
            for term in (
                "complaint",
                "shikayat",
                "problem",
                "issue",
                "pothole",
                "water",
                "paani",
                "drain",
                "streetlight",
                "garbage",
                "शिकायत",
                "समस्या",
                "पानी",
                "गड्ढा",
                "सड़क",
                "नाली",
                "बत्ती",
                "कचरा",
            )
        ):
            intent = "filing"
            reason = "contains_filing_signal"
        else:
            intent = "casual"
            reason = "no_actionable_signal"
        return IntentClassification(intent=intent, confidence=0.5, reason_code=reason)

    def extract_complaint(
        self,
        text: str,
        *,
        language: str | None = None,
        context: ConversationContext | None = None,
    ) -> ComplaintExtraction:
        del context
        normalized = text.casefold()
        issue_type = next(
            (
                category
                for terms, category in (
                    (("pothole",), "road"),
                    (("water",), "water"),
                    (("drain",), "drainage"),
                    (("streetlight",), "streetlight"),
                    (("garbage", "कचरा"), "garbage"),
                    (("गड्ढा", "सड़क"), "road"),
                    (("नाली",), "drainage"),
                    (("बत्ती",), "streetlight"),
                )
                if any(term in normalized for term in terms)
            ),
            None,
        )
        return ComplaintExtraction(
            issue_type=issue_type,
            description=text.strip() or None,
            language=language or "unknown",
            missing_fields=[] if issue_type else ["issue_type"],
            confidence=0.8 if issue_type else (0.0 if not text.strip() else 0.25),
        )
