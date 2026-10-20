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
import json
import time
import uuid
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("amverio")

MODEL = os.environ.get("AMVERIO_MODEL", "gpt-4.1")
MAX_TOOL_HOPS = 6          # safety cap on chained tool calls per turn
MAX_TURNS_PER_THREAD = 60  # safety cap on messages kept per thread
THREAD_TTL_SECONDS = 60 * 60 * 6  # drop threads untouched for 6h

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


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message.")
    if not req.thread_id:
        raise HTTPException(status_code=400, detail="Missing thread_id.")

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

    client = _client()
    messages.append({"role": "user", "content": message})

    hops = 0
    while True:
        try:
            response = client.chat.completions.create(
                model=MODEL,
                tools=_openai_tools_for(domain_id),
                messages=messages,
            )
        except Exception as e:
            log.exception("OpenAI call failed")
            raise HTTPException(status_code=502, detail=f"Upstream model error: {e}")

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            reply = msg.content or ""
            break

        hops += 1
        if hops > MAX_TOOL_HOPS:
            reply = "Sorry, something went wrong putting that together. Could you try rephrasing?"
            messages.append({"role": "assistant", "content": reply})
            break

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = run_tool(domain_id, call.function.name, args)
            log.info("tool_call thread=%s domain=%s name=%s args=%s", req.thread_id, domain_id, call.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })

    # Trim overly long threads (keep system prompt + most recent turns).
    if len(messages) > MAX_TURNS_PER_THREAD:
        messages[:] = [messages[0]] + messages[-(MAX_TURNS_PER_THREAD - 1):]

    return ChatResponse(thread_id=req.thread_id, reply=reply)


# ---------------------------------------------------------------------------
# Client Admin Portal Auth & API Endpoints
# ---------------------------------------------------------------------------
ADMIN_USERNAME = os.environ.get("AMVERIO_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("AMVERIO_ADMIN_PASSWORD", "amverio2026")
_admin_sessions: set[str] = set()


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class OrderStatusUpdate(BaseModel):
    status: str


class ReservationStatusUpdate(BaseModel):
    status: str


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


@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest, response: Response):
    if req.username == ADMIN_USERNAME and req.password == ADMIN_PASSWORD:
        token = str(uuid.uuid4())
        _admin_sessions.add(token)
        response.set_cookie(
            key="amverio_admin_token",
            value=token,
            httponly=False,
            samesite="lax",
            max_age=86400 * 7,
        )
        return {"ok": True, "token": token, "username": req.username}
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
    orders = data.ORDERS
    reservations = data.RESERVATIONS
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
        "recent_orders": list(reversed(orders[-8:])),
        "recent_reservations": list(reversed(reservations[-8:])),
    }


@app.get("/api/admin/orders")
def admin_orders(_token: str = Depends(_require_admin)):
    return {"orders": list(reversed(data.ORDERS))}


@app.post("/api/admin/orders/{order_id}/status")
def admin_update_order_status(order_id: str, req: OrderStatusUpdate, _token: str = Depends(_require_admin)):
    for order in data.ORDERS:
        if order.get("id") == order_id:
            order["status"] = req.status.strip().upper()
            return {"ok": True, "order": order}
    raise HTTPException(status_code=404, detail=f"Order {order_id} not found.")


@app.get("/api/admin/reservations")
def admin_reservations(_token: str = Depends(_require_admin)):
    return {"reservations": list(reversed(data.RESERVATIONS))}


@app.post("/api/admin/reservations/{res_id}/status")
def admin_update_reservation_status(res_id: str, req: ReservationStatusUpdate, _token: str = Depends(_require_admin)):
    for res in data.RESERVATIONS:
        if res.get("id") == res_id:
            res["status"] = req.status.strip().upper()
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

for _path in domain.domain_paths():
    app.add_api_route(f"/{_path}", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)
    app.add_api_route(f"/{_path}/", _demo_page, methods=["GET", "HEAD"], include_in_schema=False)


# Serve static files (index.html at root is the Amverio marketing site).
app.mount("/static", StaticFiles(directory=os.path.join(_here, "static")), name="static_dir")
app.mount("/", StaticFiles(directory=os.path.join(_here, "static"), html=True), name="static")
