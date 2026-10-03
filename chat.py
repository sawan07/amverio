"""
Text-only test harness for the Amverio agent prototype.

Run this in a terminal and talk to it like a customer/donor would over
WhatsApp. This proves out the conversation + tool-calling logic before any
WhatsApp or real-backend wiring happens, per the agreed "logic first" build
order.

Which agent persona runs (restaurant booking/ordering, or fundraising
donations) is picked by domain.py from the AMVERIO_DOMAIN environment
variable -- see domain.py for how to switch it.

Usage:
    export OPENAI_API_KEY=sk-...
    export AMVERIO_DOMAIN=fundraising   # or omit for the restaurant default
    pip install openai
    python3 chat.py
"""

import os
import sys
import json
from datetime import datetime

from openai import OpenAI

import domain

MODEL = "gpt-4.1"  # swap freely; any current OpenAI model with function calling works

# Ground the model in the real current date/time so "tomorrow", "this
# Friday", etc. resolve correctly -- without this it guesses, and guesses
# wrong (verified: it defaulted to dates in 2024 during testing).
_now = datetime.now()
SYSTEM_PROMPT = (
    f"Today's date is {_now.strftime('%A, %Y-%m-%d')}, current time {_now.strftime('%H:%M')}.\n\n"
    + domain.SYSTEM_PROMPT_BASE
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
    for t in domain.TOOL_SCHEMAS
]


def run_tool(name: str, tool_input: dict) -> dict:
    fn = domain.TOOL_FUNCTIONS.get(name)
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

    print(f"Connected. Talk to {domain.BRAND_NAME}'s assistant (Ctrl+C to quit).\n")

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
