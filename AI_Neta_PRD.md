# Product Requirements Document (PRD)
## AI Neta — Civic Grievance & Accountability Platform

---

## 1. Product Vision

AI Neta is an AI-driven civic accountability platform that helps citizens file, track, and escalate grievances against government departments — with automated follow-up, department routing, and public transparency.

It is explicitly **not**:
- A generic complaint app
- A chatbot
- A protest / activism tool

It **is**: an AI-driven *Janpratinidhi* (citizen representative) that files complaints, chases government departments on the citizen's behalf, and turns official silence into visible, trackable evidence.

Positioning: a friendly, street-smart "neta" — simple language, no overpromising, no threats, no politics — focused purely on *kaam karwana* (getting work done).

---

## 2. Goals & Success Criteria

| Goal | Success Criterion |
|---|---|
| Reduce friction in filing complaints | Citizen can file a verified complaint via voice, text, or photo in under 2 minutes, in Hindi/English/Hinglish |
| Ensure complaint authenticity | 100% of complaints carry live-captured photo/video, GPS, and timestamp — no gallery uploads accepted |
| Guarantee follow-through | Every complaint is auto-tracked through a defined SLA and escalation ladder (L1 → L2 → L3 → L4) with no manual intervention required |
| Convert silence into accountability | Non-response and delay are captured as structured data ("Silence Tracking") and surfaced publicly once escalation rules are breached |
| Close the loop honestly | A complaint is marked resolved **only** with proof, and only after citizen confirmation — never on department self-report alone |
| Build public trust | Department-wise response rates, pending durations, and area heatmaps are publicly viewable and exportable for RTI/legal use |
| Scale safely across India | Platform accepts complaints nationwide from day one; full automation (emails/WhatsApp/reminders) activates only in verified "active execution zones," with all other complaints in "mapping in progress" state until officer contacts are verified |

---

## 3. Feature List

### 🟥 Phase 1 — Core Launch (Non-negotiable)

**Verified Complaint Submission**
- Live camera capture only (gallery upload disabled)
- Auto GPS + timestamp capture
- Mandatory voice note for infrastructure issues
- Unique Complaint ID generation
- Submission locked from edit/delete after filing

**Multi-Channel Intake**
- Web app (PWA)
- WhatsApp (photo + voice)
- Missed-call → callback (IVR)

**Validation Engine (rule-based, non-AI)**
- Location mismatch detection
- Image clarity check
- Duplicate complaint merging
- Same-area supporter count

**AI Decision Core**
- Complaint approve/reject
- Priority scoring
- Escalation approval
- Weak-reply detection
- Public disclosure approval

**Escalation System (hard-coded ladder)**
- L1: Concerned officer
- L2: Senior officer
- L3: Department head
- L4: District/State
- Public visibility triggered on rule breach

**Automation Engine**
- Automated email dispatch
- WhatsApp notifications
- Reminder scheduling
- Append-only audit logging

**Citizen Status Tracking**
- Submitted → Sent → Pending → Escalated → Closed (with proof)

**Closure Control**
- Proof-based closure only
- Temporary fixes not counted as resolved
- Auto reopen if closure proof is missing

---

### 🟧 Phase 2 — Trust & Control

- **Tone Governor**: abuse filtering, emotional-text-to-neutral rewriting, legal-safe language enforcement
- **Area Memory**: location-wise issue history, chronic-problem tagging, repeat-issue highlighting
- **Collective Complaints**: multiple citizens can join one issue; counts visible, identities protected
- **Witness Confirmation**: 2–3 local one-tap confirmations per complaint
- **Weak Reply Intelligence**: detects "under process"/copy-paste replies, auto-CCs senior officers
- **AI Voice Status Updates**: citizen asks "Status?", gets short AI voice reply

---

### 🟨 Phase 3 — Public Transparency

- **Public Dashboard**: department response %, area heatmap, pending-duration stats
- **Public Case Pages**: timeline view, screenshot proofs, rule references, strictly neutral language
- **Media Pack Generator**: exportable PDF case bundles with date-wise evidence
- **Weekly/Monthly Reports**: ignored cases, best-performing departments, trend analysis

---

### 🟩 Admin & System

- **District Config System**: officer hierarchy, department mapping, language preference, SLA rules
- **Role-Based Access**: Admin, Moderator, Viewer, Volunteer
- **Immutable Audit Trail**: every action logged, non-editable, court/RTI-ready
- **Consent Management**: citizen consent for public disclosure, anonymity toggle
- **Admin Control Tower**: complaint heatmap, repeated-issue view, pending department-mapping queue, department responsiveness, resolution rates, expansion signals
- **Pending Department Mapping**: if no verified officer contact exists (auto-fetched or user-supplied), the complaint is accepted but held with no outbound communication until an admin verifies a contact — after which it auto-activates and the contact is remembered permanently

---

### 🟦 AI Avatar & Communication

- **AI Avatar (Spokesperson)**: daily/weekly summary videos for web and social use
- **Multi-Language Support**: Hindi + regional languages with local tone adjustment
- **Casual Conversational Mode**: everyday chit-chat, government scheme guidance, "likh de application," empathetic but non-therapeutic replies — designed to smoothly convert into an actionable complaint when relevant

---

### 🟪 Monetization-Ready (Later Stage)

- Government SaaS dashboard (internal analytics, SLA tracking, benchmarking)
- Legal/RTI export tools (one-click evidence bundles for lawyers/activists)
- Controlled data access (aggregated, anonymized data for media/research)
- Post-resolution service marketplace (local vendor leads)

---

### 🧠 Core Meta-Feature: Silence Tracking

The single feature that drives the entire system:
- Non-response is captured as data
- Delay is captured as evidence
- Patterns of delay/non-response become the basis for public accountability

---

## 4. Verification Stack (Cross-cutting requirement)

- **Image verification**: live capture, multi-frame check, reused/screenshot detection
- **Location verification**: GPS accuracy radius, image context cross-check, network sanity check
- **Identity verification**: triggered only at first complaint (Aadhaar/DL/Voter ID + liveness selfie), encrypted storage, never made public
- **Disclosure choice**: after submission, citizen chooses Anonymous (Verified Citizen) or Public (name visible) — one-time choice

---

## 5. Resolution & Escalation Logic

- SLA and escalation timelines vary by category (civic, admin, emergency-tagged)
- A department reply does **not** reset the SLA clock unless the underlying issue is actually fixed
- Case closure requires explicit citizen confirmation: Fully solved / Partially solved / Not solved
- "Not solved" reopens the loop and continues follow-up

---

## 6. Hard Guardrails — Features That Will Never Be Built

- Paid priority complaints
- Political endorsements or politician tagging
- Accusatory or shaming language toward officers
- Random advertising
- Officer-naming/shaming tools
- Legal threats or RTI/Act citations in outbound communication
- Missed-call-only complaint mode (beyond IVR intake)
- Family/village-representative filing mode
- NGO/journalist escalation shortcuts

The AI is explicitly barred from discussing politics, elections, or politician names in any conversation.

---

## 7. Launch Scope Rule

- Complaint intake, AI guidance, and tracking are available **Pan-India** from day one.
- Full automation (auto-emails, WhatsApp reminders, escalation dispatch) is enabled **only** in verified "active execution zones" (initial rollout: Madhya Pradesh).
- Complaints from non-activated regions show status "Mapping in progress" until officer contacts are verified by admin — no blind nationwide automation.

---

## 8. Final Outcome Definition (What "Done" Looks Like)

The platform is considered successful when it can demonstrably:

1. Accept a verified, tamper-resistant complaint from any citizen in under 2 minutes.
2. Route it automatically to the correct department/officer chain without manual mapping (where contacts are verified).
3. Escalate autonomously through L1–L4 on a fixed SLA with zero manual nudging.
4. Distinguish a real fix from a fake/temporary one via proof-based, citizen-confirmed closure.
5. Convert government silence and delay into a public, exportable accountability record (heatmaps, dashboards, RTI-ready bundles).
6. Operate without ever crossing into political, legal-threat, or shaming territory — staying neutral, factual, and rule-based at every step.
