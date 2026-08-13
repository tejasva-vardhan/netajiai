# Designing AI Neta for Low-Literacy & First-Time Digital Users

## Purpose
The current PRD already has good foundations for accessibility (WhatsApp, IVR, voice-first filing). This document outlines the additional design and product changes needed to make the platform genuinely usable by India's less-literate population — not just multilingual, but literacy-independent.

---

## 1. Voice-First, Not Voice-Optional

- Text chat should be treated as a **fallback**, not a default alongside voice. The primary flow — filing, checking status, receiving updates — must be fully navigable by voice and tap alone, with **zero required reading**.
- Every text-based prompt should have a spoken equivalent by default, not as an accessibility toggle.

## 2. Visual, Icon-Based Navigation

- Replace typed/read category selection with **pictograms**: broken road, no water supply, garbage not collected, streetlight not working, etc.
- Complaint category should be selectable by tapping an icon or by voice ("mera paani nahi aa raha"), never by reading a dropdown list.

## 3. Feature Phone Support

- WhatsApp and a PWA both assume a smartphone with a stable data connection. A significant share of low-literacy, low-income citizens use basic/feature phones.
- Add an **SMS or USSD-based fallback**: dial a short code, receive a callback, or respond to simple SMS prompts. This mirrors patterns already proven in Indian digital services (banking, UPI onboarding) for feature-phone users.

## 4. Confirm-Before-Submit (Read-Back)

- Before final submission, the AI should **play back / read back** the captured complaint in the citizen's own language: *"Aapne bola: sadak mein gaddha hai, sahi hai?"*
- This single step significantly reduces filing errors for users who cannot proofread text themselves, and builds confidence that the system understood them correctly.

## 5. Non-Textual Status Tracking

- The current status ladder (Submitted → Sent → Pending → Escalated → Closed) is text/dashboard-based.
- Add an **audio and color-coded equivalent**: spoken status via WhatsApp voice note or IVR callback, plus simple color/icon indicators (e.g. red/yellow/green) instead of relying on a citizen reading a status label.

## 6. Dialect Tolerance, Not Just Language Selection

- "Hindi / English / Hinglish" is a good start, but literacy-sensitive design also requires tolerance for **regional dialects** (e.g. Bundeli, Bhojpuri, Marwari), not just textbook Hindi.
- Literacy gaps are often trust gaps as much as language gaps — citizens are more likely to engage if the AI clearly understands the way they actually speak.

## 7. Trust-Building Through Explanation, Not Just Language

- Short, local-language explainer voice/video content: *"Yeh complaint kaise hoti hai, iske baad kya hota hai"* — shown or played the first time a citizen uses the platform.
- Builds confidence for first-time digital users who may be unfamiliar with how a government-linked digital process works, independent of language ability.

## 8. Physical Proof of Filing

- For a population used to physical government paperwork, an optional **printed or SMS-based receipt with the Complaint ID** can matter more for trust than a purely digital status page.
- Consider allowing citizens to request a physical/printed slip through partner touchpoints, so a filed complaint feels as "real" as a government form.

---

## Summary Principle

Every core interaction — filing, confirming, tracking, and receiving updates — should be fully completable by a citizen who **cannot read**, using voice and visual cues alone. Text and dashboards should be an enhancement for literate users, never a requirement for basic literate users.
