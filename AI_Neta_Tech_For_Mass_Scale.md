# Tech Architecture for AI Neta at National, Government-Backed Scale

## Purpose
This document outlines what changes in the technology approach if AI Neta is meant to be used by the Indian public **en masse**, carrying government backing/legitimacy, but running as its own independent platform (not integrated into existing government systems). Serving hundreds of millions of citizens reliably is a fundamentally different engineering problem than an MVP SaaS build — closer to Aadhaar/UPI/CoWIN-scale infrastructure than a typical startup stack.

---

## 1. Core Architecture: Event-Driven, Not Monolithic

- Complaint intake, AI classification, verification, notification, and escalation should run as **independent services communicating via a message broker** (Kafka or RabbitMQ), rather than direct synchronous calls between services.
- This is essential at scale — a spike in complaints from one state (e.g. during monsoon season) should never create latency or downtime for citizens filing elsewhere.
- Deploy on **Kubernetes** for horizontal auto-scaling of stateless services (API layer, AI orchestration, notification workers).

## 2. Database Layer Built for Scale From Day One

- PostgreSQL remains a reasonable system of record, but at national scale it needs **read replicas and partitioning/sharding** (e.g. by state or district), or a distributed Postgres-compatible variant (Citus, YugabyteDB).
- Complaint photos and videos should live in **object storage** (S3-compatible, CDN-backed), never in the primary database.
- **Audit logs** (append-only, immutable, court/RTI-ready) have a different access pattern than transactional complaint data — they warrant a separate write-once log store, potentially with tamper-evident hashing, rather than a Postgres table with no-update triggers.

## 3. AI & Voice Stack: Designed for Cost at Mass Scale

The current local/provider baseline uses Mistral for bounded language tasks and
Deepgram for speech-to-text. Per-call API billing remains acceptable only with
strict quotas and budget controls; at millions of voice complaints per month,
self-hosted or subsidized India-language inference should be evaluated against
measured volume, quality, residency, and GPU economics.

- **Self-host open models** where feasible — Whisper-class speech-to-text and Llama-class language models can run on owned/rented GPU infrastructure at a fraction of per-token API cost at high volume.
- **Bhashini** (India's national language AI initiative) is worth adopting specifically because it is tuned for Indian languages and dialects and is free or heavily subsidized for public-interest platforms — a meaningful cost and quality advantage at this scale, independent of any government-integration consideration.
- AI avatar/video generation should be reserved for periodic public-facing summary content (e.g. weekly public updates), not personalized per-user video, which is expensive to run at population scale.

## 4. Identity Verification: Aadhaar/DigiLocker as an Infrastructure Choice

- At the scale of hundreds of millions of citizens, **Aadhaar eKYC / DigiLocker** is the most realistic path to fast, fraud-resistant identity verification.
- Building an independent KYC pipeline (e.g. third-party vendors like HyperVerge/Onfido) at this scale is both costlier and less trusted by citizens than something backed by UIDAI.
- This is a scale-and-trust decision, not a government-integration requirement — citizens are simply more likely to trust and complete ID verification through a system they already recognize.

## 5. Data Residency & Compliance

A platform handling citizen ID data, GPS locations, and complaint content for the entire country needs to meet a high bar regardless of its integration status:

- **DPDP Act, 2023** compliance is mandatory.
- Hosting on **India-resident data centers** (private cloud regions within India, e.g. AWS/GCP/Azure India regions) matters both legally and for public trust — "government-backed" combined with citizen data hosted overseas is a difficult combination for adoption.
- **CERT-In empanelled security audits** become close to essential once processing this volume of sensitive data — a serious breach at national scale would be a major public event, government-backed or not.

## 6. Reach & Connectivity: Designed for India's Real Network Conditions

- **Offline-first mobile app** (native — React Native or Flutter, not just a PWA) that queues a complaint locally and syncs once connectivity returns, since a large share of target users are in low-bandwidth or intermittent-network areas.
- **Client-side media compression** before upload, since uncompressed photo/video uploads from 2G/3G connections will frequently fail or time out.
- **SMS/USSD/IVR fallback** — not only a literacy feature, but also a connectivity-resilience feature for areas with poor data coverage.

## 7. Reliability Engineering

At population scale, failure is a trust event, not just a technical incident.

- Full observability stack (**Prometheus/Grafana** for metrics, **ELK/Loki** for logs) with alerting specifically on SLA-breach spikes and escalation-engine failures, not just generic system errors.
- **Multi-region deployment with disaster recovery** — downtime during a crisis period (e.g. flood response) would be reputationally damaging for a platform positioned as a citizen accountability layer.
- **Anti-abuse infrastructure built for coordinated, at-scale misuse** — bot-filed complaints, brigading a specific department, or fake evidence uploads — not just individual-user rate limiting. A public, government-backed platform is a natural target for this kind of abuse.

---

## Summary Principle

The original MVP stack (FastAPI, Next.js, PostgreSQL, pay-per-call AI APIs) is well suited to proving the product works. Scaling it to serve the Indian public at large, under government backing, is roughly a **10–50x increase in engineering rigor**, not a simple technology swap. The key shifts are:

1. Event-driven microservices instead of a monolith
2. Self-hosted or subsidized AI/voice infrastructure instead of pay-per-call APIs
3. Aadhaar-grade identity verification instead of third-party KYC
4. India-resident, audited infrastructure instead of a generic cloud deployment
5. Offline-first, low-bandwidth-tolerant client design instead of a standard PWA
