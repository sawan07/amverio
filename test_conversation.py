"""
Non-interactive test run: feeds scripted customer messages through the same
loop chat.py uses, so we can see how the agent actually behaves (does it ask
for name/phone, does it confirm before booking, does it stay on topic) without
needing a live terminal to type into.
"""

import os
import json
from datetime import datetime
from openai import OpenAI
from tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

MODEL = "gpt-4.1"

with open("system_prompt.md") as f:
    _base_prompt = f.read()

_now = datetime.now()
SYSTEM_PROMPT = (
    f"Today's date is {_now.strftime('%A, %Y-%m-%d')}, current time {_now.strftime('%H:%M')}.\n\n"
    + _base_prompt
)

OPENAI_TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
    for t in TOOL_SCHEMAS
]


def run_tool(name, tool_input):
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**tool_input)
    except Exception as e:
        return {"error": str(e)}


def run_scenario(client, title, turns):
    print(f"\n{'='*70}\nSCENARIO: {title}\n{'='*70}")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user_msg in turns:
        print(f"\nYou: {user_msg}")
        messages.append({"role": "user", "content": user_msg})
        while True:
            response = client.chat.completions.create(model=MODEL, tools=OPENAI_TOOLS, messages=messages)
            message = response.choices[0].message
            messages.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                print(f"Assistant: {message.content}")
                break
            for call in message.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                result = run_tool(call.function.name, args)
                print(f"  [tool call] {call.function.name}({args}) -> {json.dumps(result)}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})


def main():
    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)

    run_scenario(client, "Table booking, info given upfront", [
        "Hi, can I book a table for 4 people this Friday at 7pm? My name's Alex Morgan, phone 07123456789.",
    ])

    run_scenario(client, "Table booking, info withheld (should ask for name/phone)", [
        "Table for 2 tomorrow at 8pm please.",
    ])

    run_scenario(client, "Food order for pickup", [
        "What's on the menu?",
        "I'll get two chargrilled chicken burgers and a side of fries, for pickup. I'm Sam Lee, 07000111222.",
    ])

    run_scenario(client, "Delivery order (no delivery logistics exist yet)", [
        "Can I get a fish and chips delivered? Priya Shah, 07222333444.",
    ])

    run_scenario(client, "Off-topic question (should stay on topic)", [
        "Random question, what's today's weather like?",
    ])

    run_scenario(client, "Overbooking a table that doesn't fit (12 people)", [
        "Table for 12 tonight at 7, name Jordan, 07999888777.",
    ])


if __name__ == "__main__":
    main()
