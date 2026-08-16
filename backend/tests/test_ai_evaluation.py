from backend.app.ai.evaluation import IntentEvaluationCase, evaluate_intent
from backend.app.ai.fakes import FakeAgentOrchestrator


def test_low_literacy_multilingual_intent_evaluation_is_a_deterministic_gate():
    cases = (
        IntentEvaluationCase("casual-1", "Namaste AI Neta", "casual"),
        IntentEvaluationCase("scheme-1", "Mujhe yojana ki eligibility batao", "scheme"),
        IntentEvaluationCase("scheme-2", "इस योजना के लिए पात्रता क्या है", "scheme"),
        IntentEvaluationCase("filing-1", "Gali mein paani jama hai", "filing"),
        IntentEvaluationCase("filing-2", "सड़क में बड़ा गड्ढा है", "filing"),
        IntentEvaluationCase("filing-3", "Mere area mein sadak par gaddha hai", "filing"),
        IntentEvaluationCase("filing-4", "Nali overflow ho rahi hai", "filing"),
        IntentEvaluationCase("filing-5", "Kachra nahi uthaya", "filing"),
        IntentEvaluationCase("status-1", "Meri complaint ka status batao", "status"),
        IntentEvaluationCase("status-2", "शिकायत की स्थिति क्या है", "status"),
        IntentEvaluationCase("status-3", "Meri sadak wali shikayat ka kya haal hai", "status"),
        IntentEvaluationCase("status-4", "Complaint kahan tak pahunchi?", "status"),
    )

    report = evaluate_intent(FakeAgentOrchestrator(), cases)

    assert report.total == len(cases)
    assert report.correct == len(cases)
    assert report.accuracy == 1.0
    assert report.failures == ()
