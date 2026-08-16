import pytest

from backend.app.ai.agno_adapter import AgnoAgentOrchestrator
from backend.app.config import Settings
from backend.app.infrastructure.ai import AgnoConfigurationError, build_agno_orchestrator


def test_agno_factory_builds_tool_free_agents_without_calling_provider():
    orchestrator = build_agno_orchestrator(
        Settings(
            environment="test",
            ai_provider="mistral",
            ai_model="test-model",
            mistral_api_key="test-key",
        )
    )

    assert isinstance(orchestrator, AgnoAgentOrchestrator)
    assert orchestrator.intent_agent.name == "aineta-intent-router"
    assert orchestrator.complaint_agent.name == "aineta-complaint-extractor"
    assert orchestrator.casual_agent.name == "aineta-casual-chat"


def test_agno_factory_rejects_unapproved_provider_before_importing_model():
    with pytest.raises(AgnoConfigurationError, match="AI_PROVIDER=mistral"):
        build_agno_orchestrator(
            Settings(environment="test", ai_provider="unapproved", ai_model="model")
        )
