# Amverio — Agent Prototype

Text-chat prototype for Amverio. The same agent core runs **two verticals
off one codebase**:

- **restaurant** — "The Copper Fork": books a table, or takes a food order
  for pickup/delivery.
- **fundraising** — "Bright Horizons Trust": lists campaigns/causes and
  takes a donation (amount, cause, one-off/monthly, Gift Aid, dedication,
  anonymity).

No real backend and no real payment on either vertical yet — by design,
per the agreed "logic first" build order.

## Two ways to run it, two different switching models

**Web demo (`app.py`) — a picker screen, no redeploy needed.** Open the
page and you're shown a card per available agent ("The Copper Fork" /
"Bright Horizons Trust"); picking one starts a conversation with that
agent. Both are live in the same running server at the same time -- there
is nothing to configure or redeploy to go from one to the other, which is
exactly what you want live in a meeting: click "Switch agent" and pick the
other card. Each conversation thread remembers which domain it started as
server-side, so two people (or two tabs) can talk to different agents on
the same deployment at once without interfering with each other.

**Terminal harness (`chat.py`) — one domain per run, via an env var.**
There's no picker in a terminal, so `chat.py` still reads `AMVERIO_DOMAIN`
once at startup and runs as exactly one agent for that whole session:

```
export AMVERIO_DOMAIN=fundraising   # or omit for the restaurant default
```

Both are backed by the same `domain.py` registry (`get_domain(id)` /
`list_domains()` / `DOMAIN_IDS`) -- adding a third vertical later means
adding one loader function there; neither `app.py`'s picker nor `chat.py`'s
env-var switch needs to change.

## Files

Shared / domain-agnostic:
- `domain.py` — the domain registry described above. `app.py`/`chat.py` only ever go through here, never import `tools.py`/`fundraising_tools.py` directly.
- `app.py` — FastAPI web server exposing `/api/domains`, `/api/new-thread`, `/api/chat`, serving the chat UI. This is what runs on the demo subdomain.
- `chat.py` — terminal chat loop wired to the OpenAI API (local testing only).
- `static/index.html` — the browser chat UI: a picker screen (fetches `/api/domains`, renders one card per agent) plus the chat screen itself, branded per the selected domain. One HTML file serves every vertical.
- `Dockerfile`, `requirements.txt`, `.dockerignore` — for deploying `app.py` as a container.

Restaurant domain:
- `data.py` — demo persona ("The Copper Fork"), tables, menu, in-memory storage.
- `tools.py` — tool functions (book_table, place_order, etc.) plus their schemas.
- `system_prompt.md` — the restaurant agent's instructions/personality/guardrails.
- `test_conversation.py` — scripted end-to-end test scenarios.

Fundraising domain:
- `fundraising_data.py` — demo persona ("Bright Horizons Trust"), campaigns, in-memory donations.
- `fundraising_tools.py` — tool functions (get_campaigns, create_donation) plus their schemas.
- `fundraising_system_prompt.md` — the fundraising agent's instructions/personality/guardrails.
- `test_fundraising_conversation.py` — scripted end-to-end test scenarios (always exercises the fundraising domain specifically, regardless of any ambient env var).

## To run it locally (terminal)

```
export OPENAI_API_KEY=sk-...
export AMVERIO_DOMAIN=fundraising   # optional, defaults to restaurant
pip install openai
python3 chat.py
```

Restaurant: talk to it as a customer would -- "can I book a table for 4 on
Friday at 7?" or "I'd like to order two burgers and fries for pickup."

Fundraising: talk to it as a donor would -- "I'd like to donate £50 to the
winter appeal" or "what causes are you running right now?"

## To run the web version locally

```
export OPENAI_API_KEY=sk-...
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open `http://localhost:8000` -- you'll see the picker screen first. Pick
either agent to start talking to it; "Switch agent" at any point returns
to the picker without losing the other agent's availability. "New order" /
"New donation" starts a fresh conversation thread in the SAME domain you're
already in.

## Deploying to the demo subdomain (Coolify)

This is meant to go live at `amverio.prologicsw.com` via Coolify on the
Hetzner server:

1. Push this folder to a git repository Coolify can reach.
2. In Coolify, create a new application from that repo, build pack
   **Dockerfile** (the `Dockerfile` here needs no changes), and set the app's
   **port to 8000**.
3. Under the app's environment variables, add `OPENAI_API_KEY` with a real
   key — set directly in Coolify, never committed to the repo. Optionally
   set `AMVERIO_MODEL` to override the default (`gpt-4.1`). `AMVERIO_DOMAIN`
   is NOT read by the web demo (both verticals are always live via the
   picker) -- it only matters if you're running `chat.py` on the server
   directly, which isn't the normal path.
4. Under the app's domain settings, set the domain to
   `amverio.prologicsw.com`. Coolify/Traefik handles the TLS certificate.
5. Deploy. `GET /healthz` returns `{"ok": true, "domains": ["restaurant", "fundraising"]}`
   once it's up — useful for confirming both agents actually deployed, and
   for Coolify's health check if you want one.

Notes for this demo deployment specifically:
- Conversation state is in-memory per `thread_id` (including which domain
  it belongs to) and is lost on restart or redeploy — fine for a demo, not
  for production traffic.
- There's no auth and no rate limiting on `/api/chat` yet — don't link this
  subdomain anywhere it'll get indexed or hammered before that's added.
- Logs print each tool call with its domain (`tool_call thread=... domain=... name=...`) — useful for watching what each agent actually does during a demo.

## Tested and verified

**Restaurant domain.** Tool functions were tested directly first
(availability checking, table assignment with fallback to the next free
table, reservation creation, order total calculation) — all correct. The
full conversation was then run end to end against the real model
(`test_conversation.py`, ten scenarios covering booking, ordering,
cancelling, rescheduling, mid-conversation order changes, staying on topic,
and overbooking) — all passing. One real bug was found and fixed along the
way: the model had no idea what today's actual date was, so "this Friday" /
"tomorrow" resolved to dates from 2024 — fixed by injecting the real
current date/time into the system prompt at the start of every
conversation. UK phone numbers are validated in `tools.py` before a booking
or order is created (`book_table` / `place_order` reject anything that
doesn't look like a real UK mobile/landline number) — format only, not a
live reachability check.

**Fundraising domain.** `fundraising_tools.py`'s `create_donation` was unit
tested directly first (zero/negative amount, unknown campaign, invalid
email, bad frequency, a dedication missing its name, Gift Aid bonus
calculation, campaign totals updating) — all correct. The full conversation
was then run end to end against the real model
(`test_fundraising_conversation.py`, six scenarios): donating with every
detail given upfront, a donor who doesn't know which cause to pick (agent
correctly offers the list via `get_campaigns`), a dedication "in memory of"
someone, recovering when an email is given in a mangled format, staying on
topic when asked something unrelated, and handling a £0 donation attempt
gracefully. All passed. One thing worth knowing, not a bug: the model
sometimes guesses a lowercase campaign slug (e.g. `winter_shelter_appeal`)
before the real id (`WINTER25`) -- `create_donation`'s validation catches
this and the model correctly calls `get_campaigns` and retries with the
right id, so the donor never sees it. The restaurant domain's tools show
the same self-correcting pattern with menu/table ids.

**Domain registry and multi-domain serving.** `domain.py`'s registry was
unit tested directly: `get_domain()` is case-insensitive, caches rather
than re-importing on every call, raises `KeyError` on an unknown id, and
`list_domains()` never leaks `tool_functions`/`tool_schemas` to the public
branding payload. `app.py` and `chat.py` both import and construct
correctly for every registered domain, and an unrecognised
`AMVERIO_DOMAIN` makes `chat.py` fail loudly at startup rather than
silently misbehaving.

The actual HTTP layer was then tested end to end by running `app.py` under
`uvicorn` and driving it with real requests: created one thread per domain,
confirmed `/api/new-thread` rejects an unknown domain (400) and `/api/chat`
rejects an unknown/expired `thread_id` (404), then sent messages to both
threads interleaved -- each reply came from the correct agent (the
restaurant thread listed the menu; the fundraising thread listed
campaigns), and critically, asking the restaurant thread to "donate £50"
and the fundraising thread to "book a table" were both correctly declined
by the agent as outside what it can do -- proving a thread's domain
binding can't leak or be confused between agents even when two
conversations are interleaved on the same running server.

## Known simplifications (intentional, for this stage)

- All data is in-memory and resets on restart — not a real database.
- No payment integration on either domain — restaurant orders are recorded
  as "pay on collection/delivery"; donations are recorded as "PLEDGED" with
  a note that a secure payment link would be sent next.
- No real delivery logistics — "delivery" is just a label on a restaurant order.
- Gift Aid on the fundraising side is a self-declared yes/no from the donor
  used to calculate the bonus shown back to them -- a real HMRC Gift Aid
  declaration also needs the donor's full name and home address, which this
  demo doesn't collect.
- No WhatsApp — this is a terminal/web chat, standing in for it.
- Both personas ("The Copper Fork", "Bright Horizons Trust") are invented
  demo personas and can be swapped freely before anything goes live.

## Next steps once this works well in testing

1. Point `tools.py`'s table-booking functions at the real
   `booking-system-backend` API instead of the in-memory list (reuses the
   existing `AvailabilityEngine` — table booking is structurally the same
   as staff/appointment booking).
2. Add real menu/order persistence to the backend (new tables, not reusing
   anything that exists today). Same idea applies to fundraising
   donations/campaigns once that vertical moves past demo.
3. Wire `chat.py`'s loop into a WhatsApp webhook via a BSP (Twilio,
   360dialog, etc.) instead of a terminal input() loop -- each WhatsApp
   business number would map to one domain, similar to how the web picker
   maps a card click to one.
4. Decide and add the real payment step (Stripe/GoCardless for donations,
   a card/online option for restaurant orders) once each vertical's
   conversation flow is proven out.
