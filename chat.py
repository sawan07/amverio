"""
Text-only test harness and conversation engine for the Amverio agent prototype.

Provides:
- respond(session_id, user_text, domain_id="restaurant", client=None) -> str:
  Single conversational turn execution with session history tracking.
- Interactive terminal chat loop when run directly: python chat.py
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("amverio.chat")

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

from openai import OpenAI
import domain

MODEL = os.environ.get("AMVERIO_MODEL", "gpt-4.1")

# Conversation history kept per session in memory
# TODO: Persist session history to SQLite/PostgreSQL store in future persistence card
SESSIONS: dict[str, dict] = {}
SESSION_TTL_SECONDS = 60 * 60 * 6  # 6 hours TTL


def _evict_stale_sessions() -> None:
    now = time.time()
    stale = [sid for sid, s in SESSIONS.items() if now - s.get("last_seen", 0) > SESSION_TTL_SECONDS]
    for sid in stale:
        SESSIONS.pop(sid, None)


def _build_system_prompt(domain_cfg: dict) -> str:
    now = datetime.now()
    return (
        f"Today's date is {now.strftime('%A, %Y-%m-%d')}, current time {now.strftime('%H:%M')}.\n\n"
        + domain_cfg["system_prompt_base"]
    )


def _get_or_create_session(session_id: str, domain_id: str) -> dict:
    _evict_stale_sessions()
    if session_id not in SESSIONS:
        domain_cfg = domain.get_domain(domain_id)
        SESSIONS[session_id] = {
            "domain": domain_id,
            "messages": [{"role": "system", "content": _build_system_prompt(domain_cfg)}],
            "last_seen": time.time(),
        }
    else:
        SESSIONS[session_id]["last_seen"] = time.time()
    return SESSIONS[session_id]


def run_tool(active_domain: dict, name: str, tool_input: dict) -> dict:
    fn = active_domain["tool_functions"].get(name)
    if fn is None:
        log.error("run_tool error: Unknown tool %r (args=%s)", name, tool_input)
        return {"error": f"Unknown tool: {name}"}
    try:
        log.info("Executing tool: %s with args: %s", name, tool_input)
        result = fn(**tool_input)
        if isinstance(result, dict) and result.get("success") is False:
            log.warning("Tool %s returned failure: %s (args=%s)", name, result.get("reason"), tool_input)
        else:
            log.info("Tool %s succeeded (args=%s)", name, tool_input)
        return result
    except Exception as e:
        log.exception("Tool execution failed: tool=%s input=%s error=%s", name, tool_input, e)
        return {"error": str(e)}


def respond(
    session_id: str,
    user_text: str,
    domain_id: Optional[str] = None,
    client: Optional[OpenAI] = None,
    model: Optional[str] = None,
) -> str:
    """
    Executes one conversational turn for a given session.
    Keeps conversation history per session_id and executes tool calls autonomously.
    """
    active_domain_id = domain_id or os.environ.get("AMVERIO_DOMAIN", "restaurant").strip().lower()
    session = _get_or_create_session(session_id, active_domain_id)
    active = domain.get_domain(session["domain"])
    log.info("respond incoming: session_id=%s domain=%s text=%r", session_id, active_domain_id, user_text)

    if client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
        client = OpenAI(api_key=api_key)

    active_model = model or MODEL
    tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in active["tool_schemas"]
    ]

    messages = session["messages"]
    messages.append({"role": "user", "content": user_text})

    # Loop to resolve LLM tool calling hops
    while True:
        response = client.chat.completions.create(
            model=active_model,
            tools=tools,
            messages=messages,
        )
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            session["last_seen"] = time.time()
            reply = msg.content or ""
            log.info("respond reply: session_id=%s preview=%r", session_id, reply[:120] if reply else "")
            return reply

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = run_tool(active, call.function.name, args)
            log.info("respond tool finished: session=%s tool=%s args=%s -> result=%s", session_id, call.function.name, args, result)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY first (see the top of this file).")
        sys.exit(1)

    domain_id = os.environ.get("AMVERIO_DOMAIN", "restaurant").strip().lower()
    try:
        active = domain.get_domain(domain_id)
    except KeyError:
        print(f"Unknown AMVERIO_DOMAIN={domain_id!r}. Expected one of: {', '.join(domain.DOMAIN_IDS)}")
        sys.exit(1)

    session_id = f"terminal-{int(time.time())}"
    print(f"Connected. Talk to {active['brand_name']}'s assistant (Ctrl+C to quit).\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not user_input:
            continue

        try:
            reply = respond(session_id, user_input, domain_id=domain_id)
            print(f"Assistant: {reply}\n")
        except Exception as e:
            print(f"Error: {e}\n")


if __name__ == "__main__":
    main()
