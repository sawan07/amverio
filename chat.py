"""
Text-only test harness for the Amverio restaurant agent prototype.

Run this in a terminal and talk to it like a customer would over WhatsApp.
This proves out the conversation + tool-calling logic before any WhatsApp
or real-backend wiring happens, per the agreed "logic first" build order.

Usage:
    export OPENAI_API_KEY=sk-...
    pip install openai
    python3 chat.py
"""

import os
import sys
import json
from datetime import datetime

from openai import OpenAI

from tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

MODEL = "gpt-4.1"  # swap freely; any current OpenAI model with function calling works

with open("system_prompt.md") as f:
    _base_prompt = f.read()

# Ground the model in the real current date/time so "tomorrow", "this
# Friday", etc. resolve correctly -- without this it guesses, and guesses
# wrong (verified: it defaulted to dates in 2024 during testing).
_now = datetime.now()
SYSTEM_PROMPT = (
    f"Today's date is {_now.strftime('%A, %Y-%m-%d')}, current time {_now.strftime('%H:%M')}.\n\n"
    + _base_prompt
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
    for t in TOOL_SCHEMAS
]


def run_tool(name: str, tool_input: dict) -> dict:
    fn = TOOL_FUNCTIONS.get(name)
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

    print("Connected. Talk to The Copper Fork's assistant (Ctrl+C to quit).\n")

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
