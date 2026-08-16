"""Deterministic AI fake for tests and local contract development."""

from __future__ import annotations

from backend.app.contracts.ai import CasualReply, ComplaintExtraction, Intent, IntentClassification
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
            "हाँ",
        }:
            intent = "continuation"
            reason = "continuation_signal"
        elif any(
            term in normalized
            for term in (
                "status",
                "track",
                "complaint id",
                "progress",
                "update",
                "kya haal",
                "haal kya",
                "haal bata",
                "kahan tak",
                "kab tak",
                "hua ya nahi",
                "स्थिति",
                "प्रगति",
                "अपडेट",
                "कहाँ तक",
                "कब तक",
                "हुआ या नहीं",
                "शिकायत की स्थिति",
            )
        ):
            intent = "status"
            reason = "contains_status_signal"
        elif any(
            term in normalized
            for term in (
                "scheme",
                "yojana",
                "eligibility",
                "benefit",
                "योजना",
                "पात्रता",
                "लाभ",
            )
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
                "road",
                "water",
                "paani",
                "drain",
                "drainage",
                "streetlight",
                "street light",
                "garbage",
                "kachra",
                "waste",
                "overflow",
                "nali",
                "nala",
                "sadak",
                "gaddha",
                "शिकायत",
                "समस्या",
                "पानी",
                "गड्ढा",
                "सड़क",
                "नाली",
                "बत्ती",
                "कचरा",
                "जलभराव",
                "स्ट्रीट लाइट",
                "नाला",
                "कूड़ा",
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
                    (("pothole", "sadak", "gaddha"), "road"),
                    (("water", "paani", "पानी"), "water"),
                    (("drain", "drainage", "nali", "nala", "नाली", "नाला"), "drainage"),
                    (("streetlight", "street light", "batti", "बत्ती", "स्ट्रीट लाइट"), "streetlight"),
                    (("garbage", "kachra", "waste", "कचरा", "कूड़ा"), "garbage"),
                    (("गड्ढा", "सड़क"), "road"),
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

    def respond_casual(
        self,
        text: str,
        *,
        language: str | None = None,
        context: ConversationContext | None = None,
    ) -> CasualReply:
        del language, context
        if text.casefold().strip() in {"hi", "hello", "hey", "namaste", "नमस्ते"}:
            return CasualReply(text="Namaste! Main aapki civic problem samajhne aur madad karne ke liye yahan hoon.")
        return CasualReply(text="Main aapki baat sun sakta hoon. Civic problem ho to yahin likhkar complaint shuru kar sakte hain.")
