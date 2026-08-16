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


def _mistral_client_options(timeout_seconds: int) -> dict[str, Any]:
    """Adapt the pinned Mistral SDK client options across supported installs."""

    try:
        from mistralai.client.utils.retries import (  # type: ignore[import-not-found]
            BackoffStrategy,
            RetryConfig,
        )
    except ImportError:
        # Older Agno/Mistral combinations expose these names directly on the
        # model. The test environment can still construct the lazy graph with
        # that compatibility path; the deployment lock uses the SDK 2.9 API.
        return {"max_retries": 0, "timeout": timeout_seconds}
    return {
        "client_params": {
            "timeout_ms": timeout_seconds * 1000,
            "retry_config": RetryConfig(
                strategy="none",
                backoff=BackoffStrategy(1, 1, 1.0, 1),
                retry_connection_errors=False,
            ),
        }
    }


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

    model_options = _mistral_client_options(settings.ai_request_timeout_seconds)
    model = MistralChat(
        id=settings.ai_model,
        api_key=settings.mistral_api_key or None,
        temperature=0.0,
        max_tokens=512,
        # Agno 2.6.5 exposes the older max_retries/timeout names, while the
        # pinned Mistral SDK 2.9.2 accepts retry_config/timeout_ms. Keep the
        # provider-version adaptation at this infrastructure boundary so a
        # slow or failing request cannot hold a browser turn indefinitely.
        **model_options,
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
              existing complaint, including Hinglish/Hindi phrases such as
              "kya haal hai", "kahan tak pahuncha", "kab tak hoga", or
              "update batao".
            - scheme: the citizen asks about a government scheme, benefit,
              eligibility, or application. Do not classify a civic problem as
              scheme merely because the sentence is in Hindi.
            - continuation: a short confirmation such as yes, haan, or okay
              that continues the last structured session action.
            - casual: greetings or unrelated conversation.

            Examples: "Mere area mein sadak par bada gaddha hai" and
            "Gali mein paani bhar gaya" are filing. "Kya main is yojana ke liye
            eligible hoon" is scheme. "Meri complaint ka status" and
            "Meri sadak wali shikayat ka kya haal hai" are status.
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
    casual_agent = Agent(
        name="aineta-casual-chat",
        model=model,
        instructions=dedent(
            """
            Reply naturally and briefly to general citizen conversation in the
            requested language. Keep the AI Neta voice warm, respectful, and
            practical. Do not invent government facts, complaint status,
            eligibility, routing, deadlines, or identity claims. If the
            citizen appears to need a complaint, status lookup, or scheme
            information, point them to that action in one short sentence; the
            router remains the authority for changing workflow. Return only
            the requested structured schema.
            """
        ),
    )
    return AgnoAgentOrchestrator(
        intent_agent=_AgnoAgentBoundary(intent_agent),
        complaint_agent=_AgnoAgentBoundary(complaint_agent),
        casual_agent=_AgnoAgentBoundary(casual_agent),
    )
