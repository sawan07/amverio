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
python3 test_conversation.py
```

---

## Deployment (Coolify / Docker)
Deploy using the included `Dockerfile` with build port `8000`. Set the environment variables in your deployment dashboard. Health check endpoint is available at `GET /healthz`.
