from types import SimpleNamespace
from uuid import uuid4

from backend.app.ai.agno_adapter import AgnoAgentOrchestrator
from backend.app.contracts.ai import ComplaintExtraction, IntentClassification
from backend.app.contracts.conversation import ConversationContext


class RecordingAgent:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def run(self, input, *, output_schema, stream=False):
        self.calls.append({"input": input, "output_schema": output_schema, "stream": stream})
        return SimpleNamespace(content=self.content)


def test_agno_adapter_requires_structured_output_and_does_not_mutate_domain():
    intent = RecordingAgent(IntentClassification(intent="filing", confidence=0.9, reason_code="test"))
    complaint = RecordingAgent(
        ComplaintExtraction(
            issue_type="road", description="Pothole", language="en", confidence=0.8
        )
    )
    orchestrator = AgnoAgentOrchestrator(intent, complaint)

    assert orchestrator.classify_intent("I want to file a complaint").intent == "filing"
    extracted = orchestrator.extract_complaint("There is a pothole", language="en")

    assert extracted.issue_type == "road"
    context = ConversationContext(
        session_id=uuid4(),
        language="en",
        last_intent="filing",
        last_next_action="start_filing",
        turn_count=1,
        complaint_draft=ComplaintExtraction(
            issue_type="road", description=None, language="en", confidence=0.8
        ),
    )
    orchestrator.classify_intent("haan", context=context)
    assert intent.calls[0]["output_schema"] is IntentClassification
    assert complaint.calls[0]["output_schema"] is ComplaintExtraction
    assert intent.calls[0]["stream"] is False
    assert '"description": null' in intent.calls[1]["input"]
