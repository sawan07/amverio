"""
Text-only test harness for the Amverio agent prototype.

Run this in a terminal and talk to it like a customer would over WhatsApp / web chat.
This tests the conversational tool-calling logic directly.

Usage:
    export OPENAI_API_KEY=sk-...
    pip install -r requirements.txt
    python3 chat.py
"""

import os
import sys
import json
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

from openai import OpenAI

import domain

MODEL = "gpt-4.1"  # swap freely; any current OpenAI model with function calling works

DOMAIN_ID = os.environ.get("AMVERIO_DOMAIN", "restaurant").strip().lower()
try:
    ACTIVE = domain.get_domain(DOMAIN_ID)
except KeyError:
    print(f"Unknown AMVERIO_DOMAIN={DOMAIN_ID!r}. Expected one of: {', '.join(domain.DOMAIN_IDS)}")
    sys.exit(1)

# Ground the model in the real current date/time so "tomorrow", "this
# Friday", etc. resolve correctly -- without this it guesses, and guesses
# wrong (verified: it defaulted to dates in 2024 during testing).
_now = datetime.now()
SYSTEM_PROMPT = (
    f"Today's date is {_now.strftime('%A, %Y-%m-%d')}, current time {_now.strftime('%H:%M')}.\n\n"
    + ACTIVE["system_prompt_base"]
)

# Convert our provider-neutral tool schemas (name/description/input_schema)
# into OpenAI's function-calling envelope.
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in ACTIVE["tool_schemas"]
]


def run_tool(name: str, tool_input: dict) -> dict:
    fn = ACTIVE["tool_functions"].get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**tool_input)
    except Exception as e:  # keep the demo from crashing on a bad call
        return {"error": str(e)}


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY first (see the top of this file).")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print(f"Connected. Talk to {ACTIVE['brand_name']}'s assistant (Ctrl+C to quit).\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # Loop in case the model chains multiple tool calls before replying.
        while True:
            response = client.chat.completions.create(
                model=MODEL,
                tools=OPENAI_TOOLS,
                messages=messages,
            )
            message = response.choices[0].message
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                print(f"Assistant: {message.content}\n")
                break

            for call in message.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                result = run_tool(call.function.name, args)
                print(f"  [tool call] {call.function.name}({args}) -> {json.dumps(result)}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                })


if __name__ == "__main__":
    main()
