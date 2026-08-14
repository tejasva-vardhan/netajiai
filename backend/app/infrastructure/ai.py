"""Construction of the bounded Agno adapters.

This module is intentionally lazy: importing the API must not initialize a
model client or spend an inference request. Deployment code must explicitly
construct the adapter and inject it into ``create_app``.
"""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Any

from backend.app.ai.agno_adapter import AgnoAgentOrchestrator
from backend.app.config import Settings


class AgnoConfigurationError(RuntimeError):
    """Raised when the selected Agno provider cannot be constructed safely."""


@dataclass(frozen=True, slots=True)
class _AgnoAgentBoundary:
    """Adapt Agno's broad overloads to the narrow application port."""

    agent: Any

    @property
    def name(self) -> str:
        return str(self.agent.name)

    def run(self, input: str, *, output_schema: type[Any], stream: bool = False) -> Any:
        return self.agent.run(input, output_schema=output_schema, stream=stream)


def build_agno_orchestrator(settings: Settings) -> AgnoAgentOrchestrator:
    """Build narrow, tool-free agents without making a provider request."""

    if settings.ai_provider != "mistral":
        raise AgnoConfigurationError(
            "The configured Agno construction adapter currently supports AI_PROVIDER=mistral"
        )
    if not settings.ai_model.strip():
        raise AgnoConfigurationError("AI_MODEL is required for the Agno adapter")

    try:
        from agno.agent import Agent
        from agno.models.mistral import MistralChat
    except ImportError as exc:  # pragma: no cover - packaging/environment failure
        raise AgnoConfigurationError(
            "Install agno and mistralai before enabling the Mistral adapter"
        ) from exc

    model = MistralChat(
        id=settings.ai_model,
        api_key=settings.mistral_api_key or None,
        temperature=0.0,
        max_tokens=512,
    )
    intent_agent = Agent(
        name="aineta-intent-router",
        model=model,
        instructions=dedent(
            """
            Classify the citizen message into exactly one supported intent.
            Use the current message and only the approved structured session
            context supplied with it. Do not answer the citizen, invent facts,
            or call tools. Return the requested structured schema.

            Intent definitions and precedence:
            - filing: the citizen reports a local civic problem or wants to
              submit a complaint, including potholes, broken roads, water,
              drainage, garbage, streetlights, overflowing waste, or similar
              public-service failures. This includes Hindi, English, and
              Hinglish descriptions without the word complaint.
            - status: the citizen asks for the progress or receipt status of an
              existing complaint.
            - scheme: the citizen asks about a government scheme, benefit,
              eligibility, or application. Do not classify a civic problem as
              scheme merely because the sentence is in Hindi.
            - continuation: a short confirmation such as yes, haan, or okay
              that continues the last structured session action.
            - casual: greetings or unrelated conversation.

            Examples: "Mere area mein sadak par bada gaddha hai" and
            "Gali mein paani bhar gaya" are filing. "Kya main is yojana ke liye
            eligible hoon" is scheme. "Meri complaint ka status" is status.
            """
        ),
    )
    complaint_agent = Agent(
        name="aineta-complaint-extractor",
        model=model,
        instructions=dedent(
            """
            Extract only facts explicitly present in the citizen message.
            Approved session context may resolve a continuation, but it must
            not add facts to the current draft. Never infer a jurisdiction,
            officer, eligibility rule, urgency, escalation, SLA, or outcome.
            Use null for unknown fields and list every required-but-missing
            field. Return the requested structured schema and no prose outside
            it.
            """
        ),
    )
    return AgnoAgentOrchestrator(
        intent_agent=_AgnoAgentBoundary(intent_agent),
        complaint_agent=_AgnoAgentBoundary(complaint_agent),
    )
