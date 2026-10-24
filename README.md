# AMVERIO — Autonomous Web Intelligence & Agent Platform

Welcome to **AMVERIO**, a state-of-the-art autonomous conversational agent platform for modern businesses.

This repository powers:
1. **The AMVERIO Futuristic Marketing Website** (`/` -> `static/index.html`), built with the **Concept 4 Cyber Eye Aperture** design, dynamic telemetry, holographic live preview, and multi-vertical feature showcase (**ShopFlow**, **BookPulse**, **DineSync**, and **SitePulse**).
2. **The Copper Fork Live Demo Platform** (`/demo`, `/restaurant` -> `static/demo.html`), powered by **DineSync** (AI Restaurant Assistant) featuring real-time table reservations, menu browsing, food ordering (pickup & delivery), single-use Stripe payment links directly in conversation, and Brevo transactional confirmation emails.

---

## Architecture & Structure

```
├── app.py                  # FastAPI web server serving marketing site & live agent API
├── chat.py                 # Terminal interactive test harness
├── data.py                 # Restaurant persona ("The Copper Fork"), menu, and tables
├── domain.py               # Domain registry for agent verticals
├── requirements.txt        # Python package dependencies
├── system_prompt.md        # System prompt and guardrails for The Copper Fork
├── test_conversation.py    # Automated conversational test suite
├── tools.py                # Agent tools (Stripe payment link, Brevo SMTP email, table booking)
├── static/
│   ├── amverio-icon.svg    # Concept 4 emblem icon (cyber eye aperture + node)
│   ├── amverio-logo.svg    # Concept 4 primary logo with wordmark
│   ├── index.html          # AMVERIO futuristic dark-mode marketing website
│   └── demo.html           # Live interactive test platform for The Copper Fork
├── Dockerfile              # Production container definition
├── .env.example            # Environment configuration template
└── .gitignore              # Git ignore rules
```

---

## Core Features & Integrations

### 1. Stripe Sandbox Payment Links
- Generates clean, secure Stripe Checkout URLs (`https://buy.stripe.com/test_...`) directly in agent chat when an order is placed.
- Configured with `restrictions[completed_sessions][limit]=1` to ensure single-use payment sessions, preventing double charging if a customer clicks both the chat link and the email link.

### 2. Brevo Transactional Email Dispatch
- Automatically triggers upon order completion to send a branded order confirmation email with full itemised breakdown, delivery/pickup details, and payment link.
- Delivered over Brevo SMTP relay (`smtp-relay.brevo.com:587`) using verified sender `orders@amverio.co.uk`.

### 3. Concept 4 Branding & UI
- Custom SVG vectors for the iconic cyber eye aperture, stylized 'A' apex, and neon cyan central intelligence node.
- Responsive dark-mode interface with glassmorphism, glowing micro-animations, and live tool execution previews.

---

## Local Setup

### 1. Prerequisites
- Python 3.10+
- OpenAI API Key

### 2. Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the project root (see `.env.example`):
```env
OPENAI_API_KEY=sk-...
AMVERIO_MODEL=gpt-4.1

# Stripe Sandbox
STRIPE_SECRET_KEY=sk_test_...

# Brevo SMTP Relay
BREVO_API_KEY=xsmtpsib-...
SMTP_SERVER=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=your-brevo-login@domain.com
SMTP_PASSWORD=your-smtp-master-key
BREVO_SENDER_EMAIL=orders@amverio.co.uk
```

### 4. Running the Web Server
```bash
uvicorn app:app --reload --port 8000
```
- Open `http://localhost:8000/` for the AMVERIO marketing landing page.
- Open `http://localhost:8000/demo` for the Copper Fork interactive agent demo.

### 5. Running the Terminal Chat Harness
```bash
python3 chat.py
```

### 6. Running Automated Tests
```bash
pip install pytest
pytest tests --ignore=tests/scenarios        # unit + persistence tests (no API key needed)
python3 test_conversation.py                 # live-model scripted conversations (needs OPENAI_API_KEY)
```
`tests/conftest.py` points the suite at a throw-away database so it never touches your dev data.
If you run the tests another way (e.g. `python -m unittest`), set `AMVERIO_DB_PATH` to a temp file first.

---

## Data persistence

Bookings, orders, the WhatsApp 24-hour-window records and **conversation history** are stored in a database, so a restart or redeploy does not lose them.

| Setting | Meaning |
|---|---|
| `DATABASE_URL` | If set to a `postgres://` / `postgresql://` URL, PostgreSQL is used (needs `psycopg2`, already in `requirements.txt`). |
| `AMVERIO_DB_PATH` | Where the SQLite file lives when PostgreSQL is not configured. Default `./data/amverio.db` (next to the code). Missing folders are created automatically. |
| `AMVERIO_SEED_DEMO_DATA` | Default `1`: an **empty** database gets 3 sample orders and 3 sample bookings so the demo/admin portal isn't blank. Set to `0` for a real pilot so sample bookings never block real tables. |

What is stored: `reservations`, `orders` (items as JSON), `whatsapp_sessions`, `conversations` (full message history per WhatsApp/web session, restored on the next message and expired after 6 hours idle) and `counters` (so IDs such as `R0007` / `O0012` are never reused).

How it behaves:
- Tables are created on startup and the code is safe to run repeatedly (`CREATE TABLE IF NOT EXISTS`).
- SQLite runs in WAL mode with a 10-second busy timeout.
- Booking a table is **atomic**: the "is it free?" check and the insert happen in one transaction (`BEGIN IMMEDIATE` on SQLite, an advisory lock on PostgreSQL), so two simultaneous requests can never double-book a table or receive the same ID. `tests/test_persistence.py` proves this with 12 simultaneous booking attempts.
- The browser demo's chat threads (`app.py`, `/api/chat`) are still in memory; only the WhatsApp/`chat.respond()` conversations are persisted.
- Existing rows in a database file are kept; new tables are added alongside them. Note the default location moved from `./amverio.db` to `./data/amverio.db`, so if you have local dev data in the old file, move it into `data/`.

### Keeping the SQLite file across redeploys (Coolify)
A container's own filesystem is thrown away on every redeploy, so the SQLite file must live on a **persistent volume**. This repo does not change the live deployment; whoever owns Coolify needs to do this once:

1. In Coolify open the Amverio application, then **Storages** -> **Add** -> *Volume Mount*.
2. Name: `amverio-data`, **Destination path**: `/app/data`.
3. Under **Environment Variables** add `AMVERIO_DB_PATH=/app/data/amverio.db`.
4. For the real pilot also add `AMVERIO_SEED_DEMO_DATA=0` (before the first start with the new volume, or the sample rows will be inserted once).
5. Redeploy. The startup log should say `Database initialized successfully (engine=SQLite, path=/app/data/amverio.db)`.
6. Check it: make a test booking, redeploy again, and confirm the booking is still there.

Skip all of this if `DATABASE_URL` points at a managed PostgreSQL: that database already lives outside the container.

---

## Deployment (Coolify / Docker)
Deploy using the included `Dockerfile` with build port `8000`. Set the environment variables in your deployment dashboard. Health check endpoint is available at `GET /healthz`.

**Persistence:** mount a volume at `/app/data` and set `AMVERIO_DB_PATH=/app/data/amverio.db` (or use `DATABASE_URL` for PostgreSQL), otherwise data is lost on every redeploy. See *Data persistence* above for the exact Coolify steps.
