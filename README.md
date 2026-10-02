# Amverio — Restaurant Agent Prototype

Text-chat prototype for the restaurant version of Amverio: books a table, or
takes a food order for pickup/delivery. No real backend, no payment yet — by
design, per the agreed build order. It now has two front ends over the same
agent logic: a terminal chat (for local testing) and a small web chat UI
(for the public demo).

## Files

- `data.py` — demo restaurant persona ("The Copper Fork"), tables, menu, in-memory storage.
- `tools.py` — the actual tool functions (book_table, place_order, etc.) plus their schemas.
- `system_prompt.md` — the agent's instructions/personality/guardrails.
- `chat.py` — terminal chat loop wired to the OpenAI API (local testing only).
- `test_conversation.py` — scripted end-to-end test scenarios.
- `app.py` — FastAPI web server exposing `/api/chat` and `/api/new-thread`, serving the chat UI. This is what runs on the demo subdomain.
- `static/index.html` — the browser chat UI (message list, input box, "New order" button).
- `Dockerfile`, `requirements.txt`, `.dockerignore` — for deploying `app.py` as a container.

## To run it locally (terminal)

```
export OPENAI_API_KEY=sk-...
pip install openai
python3 chat.py
```

Then just talk to it as a customer would: "can I book a table for 4 on
Friday at 7?" or "I'd like to order two burgers and fries for pickup."

## To run the web version locally

```
export OPENAI_API_KEY=sk-...
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open `http://localhost:8000` — same agent, browser chat UI instead of a
terminal. Clicking "New order" starts a fresh conversation thread; the
restaurant's tables/orders data is still shared across threads, same as in
real life (one restaurant, many customers).

## Deploying to the demo subdomain (Coolify)

This is meant to go live at `amverio.prologicsw.com` via Coolify on the
Hetzner server:

1. Push this folder (or the whole `amverio-restaurant-prototype/` directory)
   to a git repository Coolify can reach.
2. In Coolify, create a new application from that repo, build pack
   **Dockerfile** (the `Dockerfile` here needs no changes), and set the app's
   **port to 8000**.
3. Under the app's environment variables, add `OPENAI_API_KEY` with a real
   key — set directly in Coolify, never committed to the repo. Optionally
   set `AMVERIO_MODEL` to override the default (`gpt-4.1`).
4. Under the app's domain settings, set the domain to
   `amverio.prologicsw.com`. Coolify/Traefik handles the TLS certificate.
5. Deploy. `GET /healthz` returns `{"ok": true}` once it's up — useful for
   Coolify's health check if you want one.

Notes for this demo deployment specifically:
- Conversation state is in-memory per `thread_id` and is lost on restart or
  redeploy — fine for a demo, not for production traffic.
- There's no auth and no rate limiting on `/api/chat` yet — don't link this
  subdomain anywhere it'll get indexed or hammered before that's added.
- Logs print each tool call (`tool_call thread=... name=...`) — useful for
  watching what the agent actually does during a demo.

## Tested and verified

The tool functions were tested directly first (availability checking, table
assignment with fallback to the next free table, reservation creation, order
total calculation) — all correct.

The full conversation was then run end to end against the real model
(`test_conversation.py`, six scenarios). Confirmed working: booking with all
details given upfront, correctly asking for name/phone when withheld,
listing the menu, confirming an order's items/total before placing it,
declining to overpromise on delivery logistics, refusing a party size too
big for any table and offering alternatives, and staying on topic when
asked something unrelated.

One real bug was found and fixed in this pass: the model had no idea what
today's actual date was, so "this Friday" / "tomorrow" resolved to dates
from 2024. Fixed by injecting the real current date/time into the system
prompt at the start of every conversation (see `chat.py`) and by having
`check_table_availability` reject any date/time that's already passed.

## Known simplifications (intentional, for this stage)

- All data is in-memory and resets on restart — not the real database.
- No payment integration — orders are recorded as "pay on collection/delivery".
- No real delivery logistics — "delivery" is just a label on the order.
- No WhatsApp — this is a terminal chat, standing in for it.
- Restaurant name/menu ("The Copper Fork") is an invented demo persona and
  can be swapped freely before anything goes live.

## Next steps once this works well in testing

1. Point `tools.py`'s table-booking functions at the real
   `booking-system-backend` API instead of the in-memory list (reuses the
   existing `AvailabilityEngine` — table booking is structurally the same
   as staff/appointment booking).
2. Add real menu/order persistence to the backend (new tables, not reusing
   anything that exists today).
3. Wire `chat.py`'s loop into a WhatsApp webhook via a BSP (Twilio,
   360dialog, etc.) instead of a terminal input() loop.
4. Decide and add the payment step once ordering itself is proven out.
