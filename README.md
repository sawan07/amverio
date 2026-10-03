# Amverio — Agent Prototype

Text-chat prototype for Amverio. The same agent core now runs **two
verticals off one codebase**, picked by an environment variable:

- **restaurant** (default) — "The Copper Fork": books a table, or takes a
  food order for pickup/delivery.
- **fundraising** — "Bright Horizons Trust": lists campaigns/causes and
  takes a donation (amount, cause, one-off/monthly, Gift Aid, dedication,
  anonymity).

No real backend and no real payment on either vertical yet — by design,
per the agreed "logic first" build order. Two front ends share whichever
domain is active: a terminal chat (for local testing) and a small web chat
UI (for the public demo).

## Switching domains (`AMVERIO_DOMAIN`)

`domain.py` reads `AMVERIO_DOMAIN` once at import time and hands `app.py`
and `chat.py` the right tools, system prompt, and UI branding. Nothing else
about the deployment changes -- same app, same container, same subdomain.

| Value (case-insensitive) | Vertical | Persona |
|---|---|---|
| `restaurant` (or unset) | Table booking + food ordering | The Copper Fork |
| `fundraising` | Campaign donations | Bright Horizons Trust |

Locally:
```
export AMVERIO_DOMAIN=fundraising   # or omit for the restaurant default
```

In Coolify: **Application → Environment Variables**, same place
`OPENAI_API_KEY` lives. Add/edit `AMVERIO_DOMAIN`, then **redeploy** --
env var changes need a redeploy to take effect, a plain restart won't pick
it up. This is exactly what's planned for Monday's fundraising demo: flip
`AMVERIO_DOMAIN` to `fundraising` and redeploy, flip it back to
`restaurant` (or remove it) afterward.

An unrecognised value raises immediately on startup rather than silently
falling back, so a typo in Coolify fails loudly in the deploy logs instead
of quietly serving the wrong agent.

## Files

Shared / domain-agnostic:
- `domain.py` — the domain switch described above. `app.py`/`chat.py` only ever import from here.
- `app.py` — FastAPI web server exposing `/api/chat`, `/api/new-thread`, `/api/config`, serving the chat UI. This is what runs on the demo subdomain.
- `chat.py` — terminal chat loop wired to the OpenAI API (local testing only).
- `static/index.html` — the browser chat UI. Fetches `/api/config` on load so branding/greeting/labels match whichever domain is active -- there's one HTML file, not one per vertical.
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
- `test_fundraising_conversation.py` — scripted end-to-end test scenarios (forces the fundraising domain regardless of the ambient env var).

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
export AMVERIO_DOMAIN=fundraising   # optional, defaults to restaurant
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open `http://localhost:8000` -- same agent, browser chat UI instead of a
terminal, branded for whichever domain is active. Clicking "New order" /
"New donation" starts a fresh conversation thread; the underlying demo data
is still shared across threads, same as in real life (one business, many
customers/donors).

## Deploying to the demo subdomain (Coolify)

This is meant to go live at `amverio.prologicsw.com` via Coolify on the
Hetzner server:

1. Push this folder to a git repository Coolify can reach.
2. In Coolify, create a new application from that repo, build pack
   **Dockerfile** (the `Dockerfile` here needs no changes), and set the app's
   **port to 8000**.
3. Under the app's environment variables, add `OPENAI_API_KEY` with a real
   key — set directly in Coolify, never committed to the repo. Optionally
   set `AMVERIO_MODEL` to override the default (`gpt-4.1`), and
   `AMVERIO_DOMAIN` to pick the vertical (see above; defaults to `restaurant`).
4. Under the app's domain settings, set the domain to
   `amverio.prologicsw.com`. Coolify/Traefik handles the TLS certificate.
5. Deploy. `GET /healthz` returns `{"ok": true, "domain": "restaurant"}`
   (or `"fundraising"`) once it's up — useful for confirming which domain
   actually deployed, and for Coolify's health check if you want one.

Notes for this demo deployment specifically:
- Conversation state is in-memory per `thread_id` and is lost on restart or
  redeploy — fine for a demo, not for production traffic.
- There's no auth and no rate limiting on `/api/chat` yet — don't link this
  subdomain anywhere it'll get indexed or hammered before that's added.
- Logs print each tool call (`tool_call thread=... name=...`) — useful for
  watching what the agent actually does during a demo.

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

Also verified: `domain.py` switches cleanly between both values (including
case-insensitively, e.g. `FUNDRAISING`), defaults to `restaurant` when
unset (no behavior change from before this split existed), and raises
immediately on an unrecognised value instead of silently misbehaving.
`app.py` and `chat.py` both import and construct correctly under either
domain.

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
   360dialog, etc.) instead of a terminal input() loop.
4. Decide and add the real payment step (Stripe/GoCardless for donations,
   a card/online option for restaurant orders) once each vertical's
   conversation flow is proven out.
