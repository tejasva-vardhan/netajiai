# 🌟 AI Neta — Your Digital Janpratinidhi

**AI Neta** is a Pan-India civic grievance platform that turns citizen voices into routed, trackable complaints. It combines **voice-first AI**, **automatic location resolution**, and a **three-tier escalation matrix (L1 → L2 → L3)** so issues reach the right department and the right officer—without citizens typing long addresses or knowing government org charts.

Built as a **GovTech / B2B-style architecture** (scalable API + PostgreSQL + multi-city officer routing), it is designed to impress **recruiters and investors** as a serious civic SaaS foundation—not a simple chatbot demo.

---

## ✅ Current Repository Health

The project is close to runnable and the core architecture is consistent:

- FastAPI app boots around `main.py` with clear startup hooks for DB schema + seed safeguards.
- Next.js frontend is wired to the backend via `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).
- PostgreSQL docker setup matches the documented `DATABASE_URL` (`localhost:5435`).
- Python source compiles cleanly (`python -m compileall .` succeeded).

Before sharing publicly, address these important items:

- If this repo was ever pushed with real keys in history, **revoke and rotate** those keys (Groq, Gmail app password, etc.) and consider rewriting Git history or treating the repo as compromised.
- Ensure `ffmpeg` is installed on the machine if you plan to use voice upload (`pydub` conversion).
- Configure `ADMIN_API_KEY` and `AUTH_SECRET_KEY` for non-local deployments.
- Install test tooling (`pytest`) if you want CI-style validation (`python -m pytest` currently unavailable on this machine).

---

## ✨ Key Features

| Capability | What it means |
|------------|----------------|
| **Voice-first AI** | Citizens can speak complaints; audio is transcribed and processed through the same pipeline as text chat—lowering friction for Hindi/English users and mobile-first contexts. |
| **Auto-geocoding (no manual address entry)** | GPS + map confirmation pin complaints to coordinates; the system resolves **city / jurisdiction** without asking users to type full addresses. |
| **B2B SaaS architecture (Pan-India DB)** | **FastAPI** + **PostgreSQL** with **states, cities, departments, and officer mappings**—ready to onboard new regions and departments as data, not code forks. |
| **Smart escalation matrix (L1, L2, L3)** | Each complaint is tied to a **department** and an **escalation chain**: local officer → zonal / commissioner → state-level—surfaced in **admin tooling** and **public tracking** so stakeholders see *who* is in the chain. |

Additional highlights: **photo attachments**, **complaint IDs** with **status tracking**, **email notifications** (with a safe dev inbox—see below), and a **Next.js** citizen + admin UI.

---

## 🛠️ Tech Stack

| Layer | Technologies |
|--------|----------------|
| **Frontend** | [Next.js](https://nextjs.org/) (App Router), [Tailwind CSS](https://tailwindcss.com/) |
| **Backend** | [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy](https://www.sqlalchemy.org/), [PostgreSQL](https://www.postgresql.org/) |
| **AI** | [Groq](https://groq.com/) (LLM inference) |
| **Maps / geo** | [Leaflet](https://leafletjs.com/) + [react-leaflet](https://react-leaflet.js.org/), [OpenStreetMap](https://www.openstreetmap.org/) / [Nominatim](https://nominatim.org/) (geocoding & search) |

---

## ⚙️ Local Setup Guide

### Prerequisites

- **Python** 3.12+ recommended (see `requirements.txt` notes for 3.14+)
- **Node.js** 18+ (for the Next.js frontend)
- **PostgreSQL** — easiest path: **Docker** (see below)

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url>
cd AINETA-chatbot
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

### 2. Start PostgreSQL (Docker)

From the repo root:

```bash
docker compose up -d
```

This exposes PostgreSQL on **localhost:5435** (see `docker-compose.yml`), matching the default `DATABASE_URL` in `.env.example`.

### 3. Create your `.env` file

Copy the example file and edit values:

```bash
copy .env.example .env
```

On macOS/Linux: `cp .env.example .env`

**`.env.example` reference** (create `.env` with at least these variables filled in):

See the repo-root **`.env.example`** for the canonical list (placeholders only; never put real keys there). After copying to `.env`, set at least **`GROQ_API_KEY`**, **`DATABASE_URL`** (password must match **`POSTGRES_PASSWORD`** in `docker-compose.yml` unless you override it), and SMTP values if you send mail.

If you already had a local Postgres volume from an older compose file, either set `POSTGRES_PASSWORD` in the environment to your previous password or reset the Docker volume once.

Set a real **`GROQ_API_KEY`** and point **`DEV_SAFE_INBOX`** at an inbox **you** control for testing.

### 4. Seed the Madhya Pradesh database (officers & cities)

With `DATABASE_URL` set and the DB running:

```bash
python seed_mp.py
```

This seeds **Madhya Pradesh** with multiple cities, departments, and **L1 / L2 / L3** officer email patterns for realistic routing demos.

### 5. Run the FastAPI backend

From the repo root (with the venv activated):

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)  
- Health: `GET /health`

### 6. Run the Next.js frontend

In a **second** terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). With no `NEXT_PUBLIC_API_URL`, the app calls **`http://localhost:8000`** directly (see `frontend/lib/api.ts`). Ensure uvicorn is on port **8000**, or set `NEXT_PUBLIC_API_URL` to match your API. You can still use the optional Next.js **`/fastapi`** rewrite in `frontend/next.config.mjs` if you prefer same-origin proxying.

---

## 🔒 Developer Safety Note — `DEV_SAFE_INBOX`

**Complaint notification emails do not go to real government inboxes during development.**

The codebase uses a **`DEV_SAFE_INBOX`** architecture:

- All outbound complaint emails are directed **only** to the address in **`DEV_SAFE_INBOX`** (see `.env` and `email_service.py`).
- Government-style addresses seeded in `seed_mp.py` (e.g. `*.gov.in` patterns) are for **realistic routing and demos**, not live delivery—until you explicitly change production SMTP and unlock real recipients.
- The admin UI can surface the same value via **`GET /api/config`** (`dev_safe_inbox`) so everyone knows where test mail lands.

**Always** keep `DEV_SAFE_INBOX` set to an address you own before enabling SMTP in shared or staging environments.

---

## 📄 License

Add your license here (e.g. MIT) when you publish the repo publicly.

---

<p align="center">
  <b>AI Neta</b> — civic tech, engineered for scale.
</p>
