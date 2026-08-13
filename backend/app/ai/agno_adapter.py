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
        response = self.intent_agent.run(
            input=_with_context(text, context),
            output_schema=IntentClassification,
            stream=False,
        )
        return _validated_content(response, IntentClassification)

    def extract_complaint(
        self,
        text: str,
        *,
        language: str | None = None,
        context: ConversationContext | None = None,
    ) -> ComplaintExtraction:
        prompt = text if not language else f"Language: {language}\nCitizen message: {text}"
        response = self.complaint_agent.run(
            input=_with_context(prompt, context),
            output_schema=ComplaintExtraction,
            stream=False,
        )
        return _validated_content(response, ComplaintExtraction)


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
