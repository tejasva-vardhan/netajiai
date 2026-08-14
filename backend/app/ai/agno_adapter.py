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

from backend.app.contracts.ai import ComplaintExtraction, IntentClassification
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

    def classify_intent(
        self, text: str, *, context: ConversationContext | None = None
    ) -> IntentClassification:
        try:
            response = self.intent_agent.run(
                input=_with_context(text, context),
                output_schema=IntentClassification,
                stream=False,
            )
            classification = _validated_content(response, IntentClassification)
        except Exception as exc:
            if not _obvious_filing_signal(text):
                raise AgnoRuntimeError("Mistral intent classification failed") from exc
            classification = None
        if _obvious_filing_signal(text):
            return IntentClassification(
                intent="filing",
                confidence=0.85,
                reason_code="deterministic_civic_signal",
            )
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
        fallback = _deterministic_complaint(text, language)
        if fallback is not None and not extraction.issue_type:
            return fallback
        return extraction


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
            "स्थिति",
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
            "pothole",
            "water problem",
            "water leakage",
            "broken road",
            "streetlight",
            "garbage",
            "drain",
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
        )
    )


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
                (("drain", "nali", "नाली"), "drainage"),
                (("streetlight", "batti", "बत्ती"), "streetlight"),
                (("garbage", "kachra", "कचरा"), "garbage"),
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
