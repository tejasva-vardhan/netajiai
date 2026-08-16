# AI Neta bounded-AI evaluation

The repository now has a provider-independent intent evaluation harness at
`backend/app/ai/evaluation.py`. It evaluates an `AgentOrchestrator` through
the same port used by the application and returns total/correct/accuracy,
confusion counts, and case IDs for failures.

`backend/tests/test_ai_evaluation.py` is a deterministic contract gate covering
English, Hindi, and Hinglish intent signals. It uses the fake adapter and never
calls a model provider. This protects the routing contract while the real Agno
model remains gated behind provider credentials and evaluation approval.

The conversation boundary also runs the deterministic
`DeterministicToneGovernor` before rendering casual responses. Its refusal
categories and explicit-threat cases are covered by
`backend/tests/test_tone_governor.py` and the conversation HTTP test. A
provider/model must not be allowed to bypass this policy. Allowed casual turns
are handled by the bounded casual-chat agent; filing and reviewed scheme turns
remain separate constrained paths, while status is a receipt lookup handoff.

Department replies use the separate deterministic
`DeterministicWeakReplyClassifier`. Its output is a review signal, not a
workflow command; the reply record is append-only and only the outcome/proof
boundary can affect lifecycle state. Before enabling provider replies, add
human-labelled Hindi/English/Hinglish fixtures and measure weak-reply
precision/recall, duplicate detection, and false-escalation risk.

Before enabling a real Agno model, add a versioned, reviewed evaluation set for
intent, extraction, language/dialect coverage, hallucination resistance, and
refusal behavior. Run it against a fixed model/provider configuration, record
the model version and prompt version, and require an explicit review when
accuracy, confusion, or safety metrics regress. Do not put raw citizen
complaints or personally identifying data in the evaluation fixtures.
