# Why a single flat agent is risky here

A single LLM handling casual chat, scheme guidance, and complaint filing in one continuous conversation is exactly the setup where you get

Context bleed — casual chat tone/persona leaking into decisions like "is this complaint valid" or "should this escalate"

Improvised critical logic — the model deciding on its own, turn by turn, whether GPS matched, whether escalation is warranted, what a department's contact is — instead of following the fixed rules the PRD already defines

Fabricated specifics — invented officer emails, invented scheme eligibility rules, invented SLA timelines — because a general chat model is optimized to keep the conversation flowing, not to say "I don't have that data"

That last one is the dangerous one for a civic platform. A hallucinated scheme eligibility answer or a fabricated department contact isn't just an annoying UX bug — it actively misleads someone trying to access a government benefit or file a real grievance.

# Why multi-agent helps — but not for the reason "separate personalities"

Multi-agent isn't valuable because it creates different "modes" for the user (you're right, the user should never feel a seam). It's valuable because it lets you give each task a narrower, more testable, more constrained system prompt and tool set, so the model has less room to drift or invent. A router with narrow specialists is structurally harder to hallucinate in than one giant prompt trying to hold every rule at once.

A reasonable pattern:

## 1. Intent Router (fast, lightweight — doesn't need a big model)

Classifies each turn: casual chat / scheme query / complaint filing / status check / continuing an existing complaint. This can be a small classifier or a cheap LLM call — it doesn't need Llama-70B-level reasoning, just accurate intent detection.

## 2. Complaint Filing — not a free-chat agent, a constrained workflow

This is the key architectural call. Given the PRD already defines a strict sequence (live photo → GPS check → voice note → AI classification → confirmation read-back → submit), this should be implemented as a deterministic state machine, with the LLM used only for two narrow jobs: extracting structured fields from what the citizen says, and generating the natural-language prompts/confirmations. The LLM should never be the thing deciding "this complaint is valid" or "this should escalate to L3" — that's rule-based backend logic per the PRD's own escalation ladder. This is the single biggest lever against hallucination: don't let the model freely decide anything that has real consequences.

## 3. Scheme/Government Info Agent — RAG-grounded, answer-only-from-retrieved-data

This agent should be hard-restricted to answer only from a retrieved, structured scheme database (not general knowledge), and should have an explicit "I don't have verified information on that" fallback instead of ever guessing at eligibility criteria.

## 4. Casual Chat Agent

General conversational agent, but scoped tightly (no medical/legal/political content, per the PRD's own guardrails), with a designed hand-off: when it detects a complaint-worthy signal, it doesn't try to file the complaint itself — it hands off to the filing workflow.

## 5. Status/Tracking — barely needs an LLM at all

Mostly a DB lookup with a templated natural-language wrapper (possibly voice-rendered). Very low hallucination surface if you keep it that way instead of letting a chat model "explain" status freely.

# The part that actually determines success: shared context

The one thing that has to be airtight is that all of this feels like one continuous conversation with “AI Neta,” never a transfer between bots. That means:

One persistent session/conversation memory across all agents

One consistent voice/persona layer for final response generation, even if the underlying reasoning came from different specialized handlers

Smooth, invisible handoffs — the router should feel like understanding, not like routing ("Chaho toh iske baad complaint bhi daal dete hain" is a good example already in the PRD of this kind of soft transition)
