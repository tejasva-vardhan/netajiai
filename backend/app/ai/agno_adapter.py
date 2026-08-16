"""Agno adapter behind the provider-neutral AI port.

The adapter receives already-configured Agno agents. Model-provider setup,
credentials, tool allowlists, and persistence remain infrastructure concerns;
the domain never imports Agno.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
import json
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from backend.app.contracts.ai import CasualReply, ComplaintExtraction, IntentClassification
from backend.app.contracts.conversation import ConversationContext


class AgentRunOutput(Protocol):
    content: Any


class ConfiguredAgnoAgent(Protocol):
    def run(self, input: str, *, output_schema: type[BaseModel], stream: bool = False) -> AgentRunOutput: ...


T = TypeVar("T", bound=BaseModel)


class AgnoRuntimeError(RuntimeError):
    """Raised when the configured Agno runtime cannot satisfy the AI contract."""


def installed_agno_version() -> str:
    try:
        return version("agno")
    except PackageNotFoundError as exc:  # pragma: no cover - packaging failure
        raise AgnoRuntimeError("Agno is not installed") from exc


def _validated_content(response: AgentRunOutput, schema: type[T]) -> T:
    content = response.content
    if isinstance(content, schema):
        return content
    if isinstance(content, (dict, BaseModel)):
        return schema.model_validate(content)
    raise AgnoRuntimeError(
        f"Agno returned {type(content).__name__}; expected {schema.__name__} data"
    )


@dataclass(frozen=True, slots=True)
class AgnoAgentOrchestrator:
    intent_agent: ConfiguredAgnoAgent
    complaint_agent: ConfiguredAgnoAgent
    casual_agent: ConfiguredAgnoAgent | None = None

    def classify_intent(
        self, text: str, *, context: ConversationContext | None = None
    ) -> IntentClassification:
        # Clear workflow language is already a bounded routing contract. Avoid
        # spending an inference request on a message whose next action is
        # unambiguous; the model remains the fallback for genuinely ambiguous
        # general conversation and new civic phrasing.
        if _obvious_status_signal(text):
            return IntentClassification(
                intent="status",
                confidence=0.85,
                reason_code="deterministic_status_signal",
            )
        if _obvious_scheme_signal(text):
            return IntentClassification(
                intent="scheme",
                confidence=0.85,
                reason_code="deterministic_scheme_signal",
            )
        if _obvious_filing_signal(text):
            return IntentClassification(
                intent="filing",
                confidence=0.85,
                reason_code="deterministic_civic_signal",
            )
        if _obvious_continuation_signal(text, context):
            return IntentClassification(
                intent="continuation",
                confidence=0.9,
                reason_code="deterministic_continuation_signal",
            )
        if _obvious_casual_signal(text):
            return IntentClassification(
                intent="casual",
                confidence=0.9,
                reason_code="deterministic_greeting_signal",
            )
        try:
            response = self.intent_agent.run(
                input=_with_context(text, context),
                output_schema=IntentClassification,
                stream=False,
            )
            classification = _validated_content(response, IntentClassification)
        except Exception as exc:
            if not (
                _obvious_status_signal(text)
                or _obvious_scheme_signal(text)
                or _obvious_filing_signal(text)
                or _obvious_continuation_signal(text, context)
            ):
                raise AgnoRuntimeError("Mistral intent classification failed") from exc
            classification = None
        if classification is None:
            raise AgnoRuntimeError("Mistral returned an invalid intent classification")
        return classification

    def extract_complaint(
        self,
        text: str,
        *,
        language: str | None = None,
        context: ConversationContext | None = None,
    ) -> ComplaintExtraction:
        # Explicit civic categories are already safe to extract locally. This
        # keeps a verification resume (which repeats the citizen's original
        # report) from waiting on a second provider call, while ambiguous
        # descriptions still use the bounded model path below.
        deterministic = _deterministic_complaint(text, language)
        if deterministic is not None:
            return deterministic
        prompt = text if not language else f"Language: {language}\nCitizen message: {text}"
        try:
            response = self.complaint_agent.run(
                input=_with_context(prompt, context),
                output_schema=ComplaintExtraction,
                stream=False,
            )
            extraction = _validated_content(response, ComplaintExtraction)
        except Exception as exc:
            fallback = _deterministic_complaint(text, language)
            if fallback is None:
                raise AgnoRuntimeError("Mistral complaint extraction failed") from exc
            return fallback
        return extraction

    def respond_casual(
        self,
        text: str,
        *,
        language: str | None = None,
        context: ConversationContext | None = None,
    ) -> CasualReply:
        if _obvious_casual_signal(text):
            return CasualReply(
                text="Namaste! Main civic problem, complaint status aur verified yojana ki jaankari mein madad kar sakta hoon."
            )
        if self.casual_agent is None:
            return CasualReply(
                text="Namaste! Main aapki baat sunne aur civic problem mein madad karne ke liye yahan hoon."
            )
        prompt = text if not language else f"Language: {language}\nCitizen message: {text}"
        try:
            response = self.casual_agent.run(
                input=_with_context(prompt, context),
                output_schema=CasualReply,
                stream=False,
            )
            return _validated_content(response, CasualReply)
        except Exception as exc:
            raise AgnoRuntimeError("Mistral casual response failed") from exc


def _with_context(text: str, context: ConversationContext | None) -> str:
    if context is None:
        return text
    serialized = json.dumps(
        context.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    )
    return (
        "Approved structured session context (not a transcript):\n"
        f"{serialized}\nCurrent citizen message:\n{text}"
    )


def _obvious_filing_signal(text: str) -> bool:
    """Keep clear civic reports on the filing path if model output is noisy."""

    normalized = text.casefold()
    if any(
        term in normalized
        for term in (
            "status",
            "track",
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
            "योजना",
            "yojana",
            "eligibility",
            "पात्रता",
        )
    ):
        return False
    return any(
        term in normalized
        for term in (
            "file a complaint",
            "file complaint",
            "report a complaint",
            "report complaint",
            "report this",
            "complaint",
            "shikayat",
            "darj",
            "दर्ज",
            "शिकायत",
            "pothole",
            "road",
            "water problem",
            "water leakage",
            "water",
            "broken road",
            "drainage",
            "streetlight",
            "street light",
            "garbage",
            "kachra",
            "waste",
            "overflow",
            "drain",
            "nali",
            "nala",
            "sadak",
            "gaddha",
            "paani",
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
    )


def _obvious_status_signal(text: str) -> bool:
    normalized = text.casefold()
    return any(
        term in normalized
        for term in (
            "status",
            "track",
            "progress",
            "update",
            "complaint id",
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
    )


def _obvious_scheme_signal(text: str) -> bool:
    normalized = text.casefold()
    return any(
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
    )


def _obvious_continuation_signal(
    text: str, context: ConversationContext | None
) -> bool:
    if context is None or context.last_next_action is None:
        return False
    return text.casefold().strip() in {
        "haan",
        "haan ji",
        "yes",
        "okay",
        "ok",
        "continue",
        "theek hai",
        "ठीक है",
        "हाँ",
    }


def _obvious_casual_signal(text: str) -> bool:
    return text.casefold().strip() in {
        "hi",
        "hello",
        "hey",
        "namaste",
        "namaskar",
        "good morning",
        "good evening",
        "kaise ho",
        "कैसे हो",
        "नमस्ते",
        "नमस्कार",
    }


def _deterministic_complaint(
    text: str, language: str | None
) -> ComplaintExtraction | None:
    normalized = text.casefold()
    issue_type = next(
        (
            issue_type
            for terms, issue_type in (
                (("pothole", "sadak", "gaddha", "सड़क", "गड्ढा"), "road"),
                (("water", "paani", "पानी"), "water"),
                (("drain", "drainage", "nali", "nala", "नाली", "नाला"), "drainage"),
                (("streetlight", "street light", "batti", "बत्ती", "स्ट्रीट लाइट"), "streetlight"),
                (("garbage", "kachra", "waste", "कचरा", "कूड़ा"), "garbage"),
            )
            if any(term in normalized for term in terms)
        ),
        None,
    )
    if issue_type is None:
        return None
    return ComplaintExtraction(
        issue_type=issue_type,
        description=text.strip(),
        language=language or "unknown",
        missing_fields=[],
        confidence=0.8,
    )
