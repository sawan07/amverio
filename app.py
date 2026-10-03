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

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI

import domain

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


# Serve the chat UI. Keep this mounted last so /api/* above takes priority.
app.mount("/", StaticFiles(directory=os.path.join(_here, "static"), html=True), name="static")
