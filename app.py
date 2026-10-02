"""
Web version of the Amverio Restaurant agent prototype.

Same agent logic as chat.py (same tools.py / data.py / system_prompt.md),
just served over HTTP instead of a terminal loop, so it can sit behind a
simple browser chat UI. Each browser tab/session keeps its own
conversation by sending a `thread_id` with every message; the "New order"
button in the UI just generates a fresh thread_id client-side, which
starts a brand new conversation here (the restaurant's tables/orders data
itself is shared across threads, same as in real life -- one restaurant,
many customers).

This is still a demo: thread history lives in memory and is lost on
restart/redeploy. No auth, no rate limiting -- fine for a demo subdomain,
not for production traffic.
"""

import os
import sys
import json
import time
import uuid
import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI

from tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("amverio-restaurant")

MODEL = os.environ.get("AMVERIO_MODEL", "gpt-4.1")
MAX_TOOL_HOPS = 6          # safety cap on chained tool calls per turn
MAX_TURNS_PER_THREAD = 60  # safety cap on messages kept per thread
THREAD_TTL_SECONDS = 60 * 60 * 6  # drop threads untouched for 6h

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, "system_prompt.md")) as f:
    _base_prompt = f.read()

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOL_SCHEMAS
]


def _system_prompt() -> str:
    # Re-grounded on every new thread so the date is always "now", not
    # whenever the server process happened to start.
    now = datetime.now()
    return (
        f"Today's date is {now.strftime('%A, %Y-%m-%d')}, current time {now.strftime('%H:%M')}.\n\n"
        + _base_prompt
    )


def run_tool(name: str, tool_input: dict) -> dict:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**tool_input)
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# In-memory thread store. {thread_id: {"messages": [...], "last_seen": ts}}
# ---------------------------------------------------------------------------
THREADS: dict[str, dict] = {}


def _get_or_create_thread(thread_id: str) -> list:
    _evict_stale_threads()
    thread = THREADS.get(thread_id)
    if thread is None:
        thread = {"messages": [{"role": "system", "content": _system_prompt()}], "last_seen": time.time()}
        THREADS[thread_id] = thread
    thread["last_seen"] = time.time()
    return thread["messages"]


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


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ChatResponse(BaseModel):
    thread_id: str
    reply: str


app = FastAPI(title="Amverio Restaurant Demo")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message.")
    if not req.thread_id:
        raise HTTPException(status_code=400, detail="Missing thread_id.")

    client = _client()
    messages = _get_or_create_thread(req.thread_id)
    messages.append({"role": "user", "content": message})

    hops = 0
    while True:
        try:
            response = client.chat.completions.create(
                model=MODEL,
                tools=OPENAI_TOOLS,
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
            result = run_tool(call.function.name, args)
            log.info("tool_call thread=%s name=%s args=%s", req.thread_id, call.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })

    # Trim overly long threads (keep system prompt + most recent turns).
    if len(messages) > MAX_TURNS_PER_THREAD:
        messages[:] = [messages[0]] + messages[-(MAX_TURNS_PER_THREAD - 1):]

    return ChatResponse(thread_id=req.thread_id, reply=reply)


@app.post("/api/new-thread")
def new_thread():
    thread_id = str(uuid.uuid4())
    _get_or_create_thread(thread_id)
    return {"thread_id": thread_id}


# Serve the chat UI. Keep this mounted last so /api/* above takes priority.
app.mount("/", StaticFiles(directory=os.path.join(_here, "static"), html=True), name="static")
