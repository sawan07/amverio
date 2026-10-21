"""
Web version of the Amverio agent prototype.

Serves EVERY registered domain (domain.DOMAIN_IDS) at once -- the browser
chat UI shows a picker screen first ("who would you like to talk to?"),
and each conversation thread remembers which domain it started as. This is
different from chat.py, the terminal harness, which has no picker and so
still runs as a single domain picked by the AMVERIO_DOMAIN environment
variable.

Each browser tab/session keeps its own conversation by sending a
`thread_id` with every message after calling POST /api/new-thread with a
`domain`; the "New order"/"New donation" button in the UI starts a fresh
thread in the SAME domain, and "Switch agent" goes back to the picker.

This is still a demo: thread history lives in memory and is lost on
restart/redeploy. No auth, no rate limiting -- fine for a demo subdomain,
not for production traffic.
"""

import os
import re
import json
import time
import uuid
import secrets
import logging
from datetime import datetime

# Load .env file if present
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    try:
        with open(_env_file) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, Request, Response, Header, Cookie, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI

import domain
import data
import db
import chat as chat_engine
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("amverio")

# Models:
# - PUBLIC_MODEL: used for open public demo visitors (fast, inexpensive, safe)
# - PRO_MODEL: used for authenticated BAs / internal team (premier model, unconstrained)
PUBLIC_MODEL = os.environ.get("AMVERIO_PUBLIC_MODEL", "gpt-4o-mini").strip()
PRO_MODEL = os.environ.get("AMVERIO_PRO_MODEL", os.environ.get("AMVERIO_MODEL", "gpt-4o")).strip()

# Limits for Public Demo
PUBLIC_MAX_INPUT_CHARS = 500
PUBLIC_MAX_TOOL_HOPS = 3
PUBLIC_MAX_TURNS = 14          # 7 user turns + 7 agent replies
PUBLIC_MAX_COMPLETION_TOKENS = 350
PUBLIC_RATE_LIMIT_WINDOW = 600 # 10 minutes
PUBLIC_MAX_REQUESTS_PER_WINDOW = 15
PUBLIC_MAX_REQUESTS_PER_DAY = 50

# Limits for Authenticated BA / Pro Demo
PRO_MAX_INPUT_CHARS = 4000
PRO_MAX_TOOL_HOPS = 6
PRO_MAX_TURNS = 60
PRO_MAX_COMPLETION_TOKENS = 1200

THREAD_TTL_SECONDS = 60 * 60 * 6  # drop threads untouched for 6h

# Public IP rate tracking: {ip: {"window": [timestamps], "day": [timestamps]}}
_public_ip_requests: dict[str, dict[str, list[float]]] = {}


def _check_public_rate_limit(ip: str) -> None:
    now = time.time()
    data = _public_ip_requests.setdefault(ip, {"window": [], "day": []})
    data["window"] = [t for t in data["window"] if now - t < PUBLIC_RATE_LIMIT_WINDOW]
    if len(data["window"]) >= PUBLIC_MAX_REQUESTS_PER_WINDOW:
        retry_after = int(PUBLIC_RATE_LIMIT_WINDOW - (now - data["window"][0]))
        raise HTTPException(
            status_code=429,
            detail=f"Public demo rate limit reached (15 messages / 10 min). Please try again in {max(1, retry_after)}s, or sign in as an authorized BA.",
        )
    data["day"] = [t for t in data["day"] if now - t < 86400]
    if len(data["day"]) >= PUBLIC_MAX_REQUESTS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="Daily public demo message limit reached. Please contact Amverio for full access or sign in with BA credentials.",
        )
    data["window"].append(now)
    data["day"].append(now)

_here = os.path.dirname(os.path.abspath(__file__))

# One OpenAI-format tool list per domain, built lazily and cached -- avoids
# rebuilding the same translation on every request.
_openai_tools_cache: dict = {}


def _openai_tools_for(domain_id: str) -> list:
    if domain_id not in _openai_tools_cache:
        cfg = domain.get_domain(domain_id)
        _openai_tools_cache[domain_id] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in cfg["tool_schemas"]
        ]
    return _openai_tools_cache[domain_id]


def _system_prompt(domain_id: str) -> str:
    # Re-grounded on every new thread so the date is always "now", not
    # whenever the server process happened to start.
    cfg = domain.get_domain(domain_id)
    now = datetime.now()
    return (
        f"Today's date is {now.strftime('%A, %Y-%m-%d')}, current time {now.strftime('%H:%M')}.\n\n"
        + cfg["system_prompt_base"]
    )


def run_tool(domain_id: str, name: str, tool_input: dict) -> dict:
    tool_functions = domain.get_domain(domain_id)["tool_functions"]
    fn = tool_functions.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**tool_input)
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# In-memory thread store. Each thread remembers which domain it belongs to,
# so /api/chat never needs the client to resend it (and can't be tricked
# into switching a thread's domain mid-conversation).
# {thread_id: {"domain": str, "messages": [...], "last_seen": ts}}
# ---------------------------------------------------------------------------
THREADS: dict[str, dict] = {}


def _evict_stale_threads() -> None:
    cutoff = time.time() - THREAD_TTL_SECONDS
    stale = [tid for tid, t in THREADS.items() if t["last_seen"] < cutoff]
    for tid in stale:
        del THREADS[tid]


def _client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Server is missing OPENAI_API_KEY.")
    return OpenAI(api_key=api_key)


class NewThreadRequest(BaseModel):
    domain: str


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ChatResponse(BaseModel):
    thread_id: str
    reply: str


app = FastAPI(title="Amverio Demo")


@app.get("/healthz")
def healthz():
    return {"ok": True, "domains": domain.DOMAIN_IDS}


@app.get("/api/domains")
def domains():
    # Public branding only (no tool schemas/functions) -- the picker screen
    # renders one card per entry.
    return {"domains": domain.list_domains()}


@app.post("/api/new-thread")
def new_thread(req: NewThreadRequest):
    try:
        domain.get_domain(req.domain)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown domain: {req.domain!r}. Expected one of: {', '.join(domain.DOMAIN_IDS)}",
        )

    _evict_stale_threads()
    thread_id = str(uuid.uuid4())
    THREADS[thread_id] = {
        "domain": req.domain,
        "messages": [{"role": "system", "content": _system_prompt(req.domain)}],
        "last_seen": time.time(),
    }
    return {"thread_id": thread_id, "domain": req.domain}


# ---------------------------------------------------------------------------
# Client Admin / BA Portal Auth & Session Management
# ---------------------------------------------------------------------------
ADMIN_USERNAME = os.environ.get("AMVERIO_ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.environ.get("AMVERIO_ADMIN_PASSWORD", "amverio2026").strip()
_admin_sessions: set[str] = set()
_login_failures: dict[str, list[float]] = {}


def _check_login_rate_limit(ip: str) -> None:
    now = time.time()
    attempts = [t for t in _login_failures.get(ip, []) if now - t < 300]
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="Too many failed login attempts. Please wait 5 minutes.")
    _login_failures[ip] = attempts


def _is_authenticated_admin(request: Request) -> bool:
    auth = request.headers.get("authorization")
    if auth and auth.startswith("Bearer "):
        token = auth.split("Bearer ", 1)[1].strip()
        if token in _admin_sessions:
            return True
    cookie_token = request.cookies.get("amverio_admin_token")
    if cookie_token and cookie_token in _admin_sessions:
        return True
    header_token = request.headers.get("x-admin-token")
    if header_token and header_token in _admin_sessions:
        return True
    return False


def _require_admin(
    request: Request,
    authorization: Optional[str] = Header(None),
    amverio_admin_token: Optional[str] = Cookie(None),
) -> str:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif amverio_admin_token:
        token = amverio_admin_token
    elif "x-admin-token" in request.headers:
        token = request.headers["x-admin-token"]

    if not token or token not in _admin_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized: Please log in to admin portal.")
    return token


@app.get("/api/auth-status")
def auth_status(request: Request):
    is_admin = _is_authenticated_admin(request)
    return {
        "authenticated": is_admin,
        "mode": "pro" if is_admin else "public",
        "model": PRO_MODEL if is_admin else PUBLIC_MODEL,
        "rate_limited": not is_admin,
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message.")
    if not req.thread_id:
        raise HTTPException(status_code=400, detail="Missing thread_id.")

    is_pro = _is_authenticated_admin(request)
    client_ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )

    if not is_pro:
        # Public visitor guardrails
        if len(message) > PUBLIC_MAX_INPUT_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"Message too long for public demo (max {PUBLIC_MAX_INPUT_CHARS} characters). Please keep prompts concise.",
            )
        _check_public_rate_limit(client_ip)
    else:
        # BA / Admin unrestricted mode
        if len(message) > PRO_MAX_INPUT_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"Message exceeds maximum character length ({PRO_MAX_INPUT_CHARS}).",
            )

    _evict_stale_threads()
    thread = THREADS.get(req.thread_id)
    if thread is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown or expired thread_id. Start a new conversation (POST /api/new-thread with a domain).",
        )
    thread["last_seen"] = time.time()
    domain_id = thread["domain"]
    messages = thread["messages"]

    # Public turn ceiling
    if not is_pro and len(messages) >= PUBLIC_MAX_TURNS:
        return ChatResponse(
            thread_id=req.thread_id,
            reply=(
                "You have reached the message limit for this public demo session. "
                "Please click **'New order'** above to start a fresh conversation, "
                "or sign in with authorized BA credentials for unlimited live demos."
            ),
        )

    # Dynamic tier selection
    selected_model = PRO_MODEL if is_pro else PUBLIC_MODEL
    max_hops = PRO_MAX_TOOL_HOPS if is_pro else PUBLIC_MAX_TOOL_HOPS
    max_tokens = PRO_MAX_COMPLETION_TOKENS if is_pro else PUBLIC_MAX_COMPLETION_TOKENS
    max_turns_retained = PRO_MAX_TURNS if is_pro else PUBLIC_MAX_TURNS

    client = _client()
    messages.append({"role": "user", "content": message})

    hops = 0
    while True:
        try:
            response = client.chat.completions.create(
                model=selected_model,
                tools=_openai_tools_for(domain_id),
                messages=messages,
                max_tokens=max_tokens,
            )
        except Exception as e:
            log.exception("OpenAI call failed (model=%s, is_pro=%s)", selected_model, is_pro)
            raise HTTPException(status_code=502, detail=f"Upstream model error: {e}")

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            reply = msg.content or ""
            break

        hops += 1
        if hops > max_hops:
            reply = "I've gathered what I can, but reached the tool execution limit for this step. Could you clarify what you'd like to do next?"
            messages.append({"role": "assistant", "content": reply})
            break

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = run_tool(domain_id, call.function.name, args)
            log.info("tool_call thread=%s domain=%s name=%s args=%s (pro=%s)", req.thread_id, domain_id, call.function.name, args, is_pro)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })

    # Trim overly long threads
    if len(messages) > max_turns_retained:
        messages[:] = [messages[0]] + messages[-(max_turns_retained - 1):]

    return ChatResponse(thread_id=req.thread_id, reply=reply)


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class OrderStatusUpdate(BaseModel):
    status: str


class ReservationStatusUpdate(BaseModel):
    status: str


@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest, request: Request, response: Response):
    client_ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    _check_login_rate_limit(client_ip)

    user_input = (req.username or "").strip()
    pass_input = (req.password or "").strip()

    valid_user = bool(ADMIN_USERNAME) and secrets.compare_digest(user_input, ADMIN_USERNAME)
    valid_pass = bool(ADMIN_PASSWORD) and secrets.compare_digest(pass_input, ADMIN_PASSWORD)

    if valid_user and valid_pass:
        _login_failures.pop(client_ip, None)
        token = str(uuid.uuid4())
        _admin_sessions.add(token)
        response.set_cookie(
            key="amverio_admin_token",
            value=token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=86400 * 7,
        )
        return {"ok": True, "token": token, "username": user_input}

    now = time.time()
    attempts = [t for t in _login_failures.get(client_ip, []) if now - t < 300]
    attempts.append(now)
    _login_failures[client_ip] = attempts
    raise HTTPException(status_code=401, detail="Invalid username or password.")


@app.post("/api/admin/logout")
def admin_logout(response: Response, token: str = Depends(_require_admin)):
    _admin_sessions.discard(token)
    response.delete_cookie(key="amverio_admin_token")
    return {"ok": True}


@app.get("/api/admin/check-auth")
def admin_check_auth(token: str = Depends(_require_admin)):
    return {"authenticated": True, "username": ADMIN_USERNAME}


@app.get("/api/admin/overview")
def admin_overview(_token: str = Depends(_require_admin)):
    orders = db.get_orders()
    reservations = db.get_reservations()
    total_sales = sum(float(o.get("total", 0)) for o in orders)
    orders_count = len(orders)
    avg_order_value = round(total_sales / orders_count, 2) if orders_count else 0.0
    active_reservations = sum(1 for r in reservations if r.get("status") in ("CONFIRMED", "SEATED"))

    return {
        "business": {
            "name": data.BUSINESS.get("name", "The Copper Fork"),
            "cuisine": data.BUSINESS.get("cuisine", "Modern British bistro & grill"),
            "currency": data.BUSINESS.get("currency", "GBP"),
            "address": data.BUSINESS.get("address", "14 Mill Lane"),
        },
        "stats": {
            "total_sales": round(total_sales, 2),
            "orders_count": orders_count,
            "reservations_count": len(reservations),
            "active_reservations": active_reservations,
            "avg_order_value": avg_order_value,
            "currency_symbol": "£",
            "active_threads": len(THREADS),
        },
        "recent_orders": orders[:8],
        "recent_reservations": reservations[:8],
    }


@app.get("/api/admin/orders")
def admin_orders(_token: str = Depends(_require_admin)):
    return {"orders": db.get_orders()}


@app.api_route("/order-success", methods=["GET", "HEAD"])
@app.api_route("/order-success/", methods=["GET", "HEAD"])
def order_success_page(request: Request, order_id: Optional[str] = None, session_id: Optional[str] = None):
    """Callback landing page when customer finishes Stripe checkout."""
    if order_id:
        db.update_order_status(order_id, "PAID")
        log.info("Order %s automatically marked as PAID upon checkout completion", order_id)
    return FileResponse(os.path.join(_here, "static", "order-success.html"))


@app.post("/api/stripe/webhook")
@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Stripe Webhook handler to automatically mark orders as PAID on successful payment."""
    try:
        body = await request.body()
        event = json.loads(body.decode("utf-8"))
    except Exception as e:
        log.warning("Invalid Stripe webhook payload: %s", e)
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("type", "")
    log.info("Stripe webhook received: %s", event_type)

    if event_type in ("checkout.session.completed", "payment_intent.succeeded"):
        data_obj = event.get("data", {}).get("object", {})
        metadata = data_obj.get("metadata", {}) or {}
        order_id = metadata.get("order_id") or data_obj.get("client_reference_id")
        if order_id:
            db.update_order_status(order_id, "PAID")
            log.info("Stripe Webhook: Order %s updated to PAID", order_id)

    return {"status": "success", "received": True}


@app.get("/api/orders/{order_id}")
def get_order_endpoint(order_id: str):
    """Retrieve public order status for receipt page or customer lookup."""
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order": order}


@app.post("/api/admin/orders/{order_id}/mark-paid")
def admin_mark_order_paid(order_id: str, _token: str = Depends(_require_admin)):
    """Allow admin to mark an order as PAID."""
    order = db.update_order_status(order_id, "PAID")
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found.")
    return {"ok": True, "order": order}


@app.post("/api/admin/orders/{order_id}/status")
def admin_update_order_status(order_id: str, req: OrderStatusUpdate, _token: str = Depends(_require_admin)):
    new_status = req.status.strip().upper()
    order = db.update_order_status(order_id, new_status)
    if order:
        return {"ok": True, "order": order}
    raise HTTPException(status_code=404, detail=f"Order {order_id} not found.")


@app.get("/api/admin/reservations")
def admin_reservations(_token: str = Depends(_require_admin)):
    return {"reservations": db.get_reservations()}


@app.post("/api/admin/reservations/{res_id}/status")
def admin_update_reservation_status(res_id: str, req: ReservationStatusUpdate, _token: str = Depends(_require_admin)):
    res = db.update_reservation_status(res_id, req.status)
    if res:
        return {"ok": True, "reservation": res}
    raise HTTPException(status_code=404, detail=f"Reservation {res_id} not found.")


@app.get("/api/admin/menu")
def admin_menu(_token: str = Depends(_require_admin)):
    return {
        "menu": data.MENU,
        "tables": data.TABLES,
        "business": {
            "name": data.BUSINESS.get("name"),
            "cuisine": data.BUSINESS.get("cuisine"),
            "currency": data.BUSINESS.get("currency"),
            "address": data.BUSINESS.get("address"),
        },
    }


# ---------------------------------------------------------------------------
# Twilio WhatsApp Webhook Endpoint
# ---------------------------------------------------------------------------
_processed_message_sids: dict[str, float] = {}
MESSAGE_SID_TTL_SECONDS = 3600  # retain SIDs for 1 hour for idempotency


def _evict_stale_message_sids() -> None:
    now = time.time()
    stale = [sid for sid, t in _processed_message_sids.items() if now - t > MESSAGE_SID_TTL_SECONDS]
    for sid in stale:
        _processed_message_sids.pop(sid, None)


def _format_for_whatsapp(text: str) -> str:
    """
    Adapts standard Markdown text to WhatsApp-native formatting:
    - Markdown bold **bold** -> *bold* (WhatsApp uses single asterisks for bold)
    - Markdown headers ### Header -> *Header*
    - Markdown links [Label](url) -> Label: url
    """
    if not text:
        return ""
    # Convert markdown links [Label](URL) -> Label: URL
    formatted = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\1: \2", text)
    # Convert markdown headers: ### Title -> *Title*
    formatted = re.sub(r"(?:^|(?<=\n)|(?<=\s))#{1,6}\s*(.+?)(?=\n|$)", r"*\1*", formatted)
    # Convert **bold** -> *bold*
    formatted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", formatted)
    return formatted.strip()


def _split_whatsapp_message(text: str, max_length: int = 1500) -> list[str]:
    """
    Splits replies longer than max_length into conversational chunks,
    preferring paragraph breaks, newlines, sentence ends, or spaces.
    """
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_length:
        split_idx = remaining.rfind("\n\n", 0, max_length)
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = remaining.rfind("\n", 0, max_length)
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = remaining.rfind(". ", 0, max_length)
            if split_idx != -1:
                split_idx += 1
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = remaining.rfind(" ", 0, max_length)
        if split_idx == -1:
            split_idx = max_length

        chunk = remaining[:split_idx].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_idx:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def _validate_twilio_signature(request: Request, form_data: dict) -> bool:
    """
    Validates X-Twilio-Signature header using Twilio's RequestValidator.
    Rejects requests without valid signatures or missing auth tokens.
    """
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if not auth_token:
        log.warning("Rejecting Twilio webhook: TWILIO_AUTH_TOKEN is not configured.")
        return False

    signature = request.headers.get("x-twilio-signature") or request.headers.get("X-Twilio-Signature")
    if not signature:
        log.warning("Rejecting Twilio webhook: missing X-Twilio-Signature header.")
        return False

    validator = RequestValidator(auth_token)

    override_url = os.environ.get("TWILIO_WEBHOOK_URL", "").strip()
    if override_url:
        candidates = [override_url]
    else:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
        url_with_proxy = f"{proto}://{host}{request.url.path}"
        candidates = [url_with_proxy, str(request.url)]

    for u in candidates:
        if validator.validate(u, form_data, signature):
            return True

    log.warning("Rejecting Twilio webhook: signature verification failed for URLs: %s", candidates)
    return False


@app.get("/webhooks/twilio/whatsapp")
def twilio_whatsapp_info():
    return {
        "status": "ready",
        "description": "Amverio Twilio WhatsApp webhook endpoint (HTTP POST expected)",
    }


@app.post("/webhooks/twilio/whatsapp")
async def twilio_whatsapp_webhook(request: Request):
    """
    Twilio WhatsApp incoming message webhook.
    Validates signature, enforces idempotency, calls chat.respond(),
    splits long replies, and returns TwiML MessagingResponse.
    """
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}

    # 1. Signature validation
    if not _validate_twilio_signature(request, form_data):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature.")

    message_sid = form_data.get("MessageSid", "").strip()
    from_number = form_data.get("From", "").strip()
    body = form_data.get("Body", "").strip()
    num_media = int(form_data.get("NumMedia", "0") or "0")

    # 2. Idempotency: ignore duplicate MessageSid
    _evict_stale_message_sids()
    if message_sid:
        if message_sid in _processed_message_sids:
            log.info("Ignoring duplicate MessageSid: %s", message_sid)
            resp = MessagingResponse()
            return Response(content=str(resp), media_type="application/xml")
        _processed_message_sids[message_sid] = time.time()

    # Track 24-hour customer window in database
    if from_number:
        try:
            db.record_whatsapp_inbound(from_number, body)
        except Exception as e:
            log.warning("Could not record WhatsApp inbound timestamp for %s: %s", from_number, e)

    # 3. Handle empty / media-only messages politely
    resp = MessagingResponse()
    if not body:
        if num_media > 0:
            resp.message("Thanks for sharing that! Currently, I can only read text messages. Please send your question or request as text.")
        else:
            resp.message("Hello! Welcome to The Copper Fork. How can I help you today with table bookings or menu orders?")
        return Response(content=str(resp), media_type="application/xml")

    # 4. Drive agent response via chat_engine.respond()
    session_id = from_number or "whatsapp-default"
    try:
        reply_text = chat_engine.respond(session_id=session_id, user_text=body, domain_id="restaurant")
    except Exception as e:
        log.exception("Error generating agent reply for %s: %s", session_id, e)
        reply_text = "I'm having a little trouble right now. Please give us a call at the restaurant or try again shortly."

    # 5. Format for WhatsApp readability (*bold*, links) & split replies > 1600 chars
    reply_text = _format_for_whatsapp(reply_text)
    chunks = _split_whatsapp_message(reply_text, max_length=1500)
    for chunk in chunks:
        resp.message(chunk)

    return Response(content=str(resp), media_type="application/xml")


@app.get("/api/whatsapp/sessions/{phone}")
def get_whatsapp_session_status(phone: str, request: Request):
    """Inspect WhatsApp session and 24-hour service window status."""
    sess = db.get_whatsapp_session(phone)
    inside_24h = db.is_inside_24h_window(phone)
    if not sess:
        return {
            "phone": phone,
            "exists": False,
            "inside_24h_window": False,
            "detail": "No inbound messages recorded from this number.",
        }
    return {
        "phone": phone,
        "exists": True,
        "inside_24h_window": inside_24h,
        "last_inbound_at": sess.get("last_inbound_at"),
        "last_outbound_at": sess.get("last_outbound_at"),
        "created_at": sess.get("created_at"),
        "updated_at": sess.get("updated_at"),
    }


@app.post("/api/reminders/run")
def trigger_booking_reminders(
    hours: float = 3.0,
    dry_run: bool = False,
    request: Request = None,
):
    """
    Manually trigger or schedule the booking reminder job.
    Requires BA/Admin authorization.
    """
    if not _is_authenticated_admin(request):
        raise HTTPException(status_code=401, detail="Unauthorized: Admin access required.")
    import reminder_job
    results = reminder_job.run_booking_reminders(hours_ahead=hours, dry_run=dry_run)
    return {
        "status": "success",
        "processed_count": len(results),
        "results": results,
    }


def _admin_page():
    return FileResponse(os.path.join(_here, "static", "admin.html"))


app.add_api_route("/admin", _admin_page, methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/admin/", _admin_page, methods=["GET", "HEAD"], include_in_schema=False)


def _demo_page():
    return FileResponse(os.path.join(_here, "static", "demo.html"))


app.add_api_route("/demo", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/demo/", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/restaurant", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/restaurant/", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/client-demo", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/client-demo/", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)

for _path in domain.domain_paths():
    app.add_api_route(f"/{_path}", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)
    app.add_api_route(f"/{_path}/", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)


# Serve static files (index.html at root is the Amverio marketing site).
app.mount("/static", StaticFiles(directory=os.path.join(_here, "static")), name="static_dir")
app.mount("/", StaticFiles(directory=os.path.join(_here, "static"), html=True), name="static")
