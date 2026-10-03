"""
Non-interactive test run for the fundraising domain -- same harness pattern
as test_conversation.py, but forces AMVERIO_DOMAIN=fundraising so it
exercises Bright Horizons Trust's tools/prompt regardless of what's set in
the environment.
"""

import os
os.environ["AMVERIO_DOMAIN"] = "fundraising"

import json
from datetime import datetime
from openai import OpenAI
import domain

MODEL = "gpt-4.1"

_now = datetime.now()
SYSTEM_PROMPT = (
    f"Today's date is {_now.strftime('%A, %Y-%m-%d')}, current time {_now.strftime('%H:%M')}.\n\n"
    + domain.SYSTEM_PROMPT_BASE
)

OPENAI_TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
    for t in domain.TOOL_SCHEMAS
]


def run_tool(name, tool_input):
    fn = domain.TOOL_FUNCTIONS.get(name)
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

    run_scenario(client, "Donation with everything given upfront", [
        "Hi, I'd like to donate £50 to the Winter Shelter Appeal. I'm a UK taxpayer so please claim Gift Aid. "
        "I'm Alex Morgan, alex.morgan@example.com. Just a one-off, no dedication, happy to be named.",
    ])

    run_scenario(client, "Donor doesn't know which cause (should offer campaigns)", [
        "I want to donate 100 quid but I'm not sure which cause to pick.",
        "Let's do the youth one. Monthly please. Not a UK taxpayer. Sam Lee, sam.lee@example.com, no dedication, keep it anonymous.",
    ])

    run_scenario(client, "Dedication in memory of someone", [
        "I'd like to give £25 in memory of my grandmother to the general fund.",
        "Yes I'm a UK taxpayer. One-off. Her name was Grandma Lee. My name's Priya Shah, priya.shah@example.com, and it's fine to show my name.",
    ])

    run_scenario(client, "Invalid email withheld then corrected", [
        "Donate £10 to winter shelter, one-off, no gift aid, no dedication, show my name. I'm Jordan Blake.",
        "My email is jordan[at]example[dot]com actually just put jordan.blake@example.com",
    ])

    run_scenario(client, "Off-topic question (should stay on topic)", [
        "Random question, what's the weather like today?",
    ])

    run_scenario(client, "Zero/invalid amount handled gracefully", [
        "I want to donate £0 to the general fund.",
    ])


if __name__ == "__main__":
    main()
