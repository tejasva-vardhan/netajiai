from types import SimpleNamespace
from uuid import uuid4

from backend.app.ai.agno_adapter import AgnoAgentOrchestrator
from backend.app.contracts.ai import CasualReply, ComplaintExtraction, IntentClassification
from backend.app.contracts.conversation import ConversationContext


class RecordingAgent:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def run(self, input, *, output_schema, stream=False):
        self.calls.append({"input": input, "output_schema": output_schema, "stream": stream})
        return SimpleNamespace(content=self.content)


class FailingAgent:
    def run(self, input, *, output_schema, stream=False):
        raise RuntimeError("provider unavailable")


def test_agno_adapter_requires_structured_output_and_does_not_mutate_domain():
    intent = RecordingAgent(IntentClassification(intent="filing", confidence=0.9, reason_code="test"))
    complaint = RecordingAgent(
        ComplaintExtraction(
            issue_type="road", description="Pothole", language="en", confidence=0.8
        )
    )
    orchestrator = AgnoAgentOrchestrator(intent, complaint)

    assert orchestrator.classify_intent("Could you help me understand this").intent == "filing"
    extracted = orchestrator.extract_complaint("The street needs attention", language="en")

    assert extracted.issue_type == "road"
    context = ConversationContext(
        session_id=uuid4(),
        language="en",
        last_intent="casual",
        last_next_action="continue_chat",
        turn_count=1,
        complaint_draft=ComplaintExtraction(
            issue_type="road", description=None, language="en", confidence=0.8
        ),
    )
    orchestrator.classify_intent("Can you help me with this?", context=context)
    assert intent.calls[0]["output_schema"] is IntentClassification
    assert complaint.calls[0]["output_schema"] is ComplaintExtraction
    assert intent.calls[0]["stream"] is False
    assert '"description": null' in intent.calls[1]["input"]


def test_agno_adapter_keeps_obvious_civic_report_on_filing_path():
    intent = RecordingAgent(
        IntentClassification(intent="scheme", confidence=0.9, reason_code="model_guess")
    )
    orchestrator = AgnoAgentOrchestrator(intent, RecordingAgent(ComplaintExtraction(
        issue_type="road", description=None, language="hi-IN", confidence=0.8
    )))

    classification = orchestrator.classify_intent("Mere area mein sadak par bada gaddha hai")

    assert classification.intent == "filing"
    assert classification.reason_code == "deterministic_civic_signal"


def test_agno_adapter_keeps_obvious_status_on_status_path_when_model_is_wrong_or_down():
    wrong_model = RecordingAgent(
        IntentClassification(intent="filing", confidence=0.9, reason_code="model_guess")
    )
    orchestrator = AgnoAgentOrchestrator(wrong_model, RecordingAgent(
        ComplaintExtraction(issue_type=None, description=None, language="hi-IN", confidence=0.0)
    ))
    text = "Meri sadak wali shikayat ka kya haal hai"

    classification = orchestrator.classify_intent(text)
    assert classification.intent == "status"
    assert classification.reason_code == "deterministic_status_signal"

    unavailable = AgnoAgentOrchestrator(FailingAgent(), FailingAgent())
    fallback = unavailable.classify_intent(text)
    assert fallback.intent == "status"


def test_agno_adapter_keeps_contextual_confirmation_on_continuation_path():
    context = ConversationContext(
        session_id=uuid4(),
        language="hi-IN",
        last_intent="filing",
        last_next_action="verify_identity",
        turn_count=1,
    )
    wrong_model = AgnoAgentOrchestrator(
        RecordingAgent(IntentClassification(intent="casual", confidence=0.9, reason_code="model_guess")),
        RecordingAgent(ComplaintExtraction(issue_type=None, description=None, language="hi-IN", confidence=0.0)),
    )
    assert wrong_model.classify_intent("haan", context=context).intent == "continuation"

    unavailable = AgnoAgentOrchestrator(FailingAgent(), FailingAgent())
    fallback = unavailable.classify_intent("हाँ", context=context)
    assert fallback.intent == "continuation"


def test_agno_adapter_fills_obvious_civic_issue_when_model_omits_it():
    intent = RecordingAgent(
        IntentClassification(intent="filing", confidence=0.9, reason_code="model_guess")
    )
    complaint = RecordingAgent(
        ComplaintExtraction(issue_type=None, description=None, language="hi-IN", confidence=0.2)
    )
    orchestrator = AgnoAgentOrchestrator(intent, complaint)

    extraction = orchestrator.extract_complaint(
        "Mere area mein sadak par bada gaddha hai", language="hi-IN"
    )

    assert extraction.issue_type == "road"
    assert extraction.description == "Mere area mein sadak par bada gaddha hai"
    assert complaint.calls == []


def test_agno_adapter_falls_back_for_common_hinglish_filing_signals():
    orchestrator = AgnoAgentOrchestrator(FailingAgent(), FailingAgent())

    for text, issue_type in (
        ("Mere area mein paani nahi aa raha", "water"),
        ("There is no water in my area", "water"),
        ("Street light band hai", "streetlight"),
        ("Nali overflow ho rahi hai", "drainage"),
        ("Kachra nahi uthaya", "garbage"),
        ("Ghar ke saamne dikkat hai sadak kharab hai", "road"),
    ):
        classification = orchestrator.classify_intent(text)
        assert classification.intent == "filing"
        assert orchestrator.extract_complaint(text, language="hi-IN").issue_type == issue_type


def test_agno_adapter_falls_back_for_generic_complaint_request_when_model_is_down():
    orchestrator = AgnoAgentOrchestrator(FailingAgent(), FailingAgent())

    classification = orchestrator.classify_intent("I want to file a complaint")

    assert classification.intent == "filing"
    assert classification.reason_code == "deterministic_civic_signal"


def test_agno_adapter_routes_general_chat_to_the_bounded_casual_agent():
    casual = RecordingAgent(CasualReply(text="Namaste, main madad kar sakta hoon."))
    orchestrator = AgnoAgentOrchestrator(
        RecordingAgent(IntentClassification(intent="casual", confidence=0.9, reason_code="greeting")),
        RecordingAgent(ComplaintExtraction(issue_type=None, description=None, language="en", confidence=0.0)),
        casual,
    )

    response = orchestrator.respond_casual("How can you help me?", language="en")

    assert response.text == "Namaste, main madad kar sakta hoon."
    assert casual.calls[0]["output_schema"] is CasualReply


def test_agno_adapter_handles_a_greeting_without_a_provider_request():
    intent = FailingAgent()
    casual = FailingAgent()
    orchestrator = AgnoAgentOrchestrator(intent, FailingAgent(), casual)

    assert orchestrator.classify_intent("Namaste").intent == "casual"
    assert "civic problem" in orchestrator.respond_casual("Namaste").text


def test_agno_adapter_keeps_verification_resume_on_filing_path_without_a_provider_call():
    intent = RecordingAgent(IntentClassification(intent="casual", confidence=0.9, reason_code="model_guess"))
    complaint = RecordingAgent(
        ComplaintExtraction(issue_type=None, description=None, language="hi-IN", confidence=0.0)
    )
    orchestrator = AgnoAgentOrchestrator(intent, complaint)
    context = ConversationContext(
        session_id=uuid4(),
        language="hi-IN",
        last_intent="filing",
        last_next_action="verify_identity",
        turn_count=1,
    )

    classification = orchestrator.classify_intent("Yahan roz pareshani ho rahi hai morning se", context=context)

    assert classification.intent == "filing"
    assert classification.reason_code == "deterministic_active_filing_context"
    assert intent.calls == []


def test_agno_adapter_falls_back_when_structured_model_output_is_invalid():
    orchestrator = AgnoAgentOrchestrator(FailingAgent(), FailingAgent(), FailingAgent())
    context = ConversationContext(
        session_id=uuid4(),
        language="hi-IN",
        last_intent="filing",
        last_next_action="start_filing",
        turn_count=2,
    )

    assert orchestrator.classify_intent("Could you help me understand this").intent == "casual"
    extraction = orchestrator.extract_complaint("Ghar ke saamne dikkat hai", language="hi-IN")
    assert extraction.issue_type is None
    assert extraction.missing_fields == ["issue_type"]
    assert "civic problem" in orchestrator.respond_casual("How can you help?", language="en").text
    assert orchestrator.classify_intent("Ghar ke saamne dikkat hai", context=context).intent == "filing"
