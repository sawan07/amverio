"""
Non-interactive test run for the JMG Cargo quotation domain -- same harness
pattern as test_fundraising_conversation.py. Always exercises the
"jmgcargo" domain regardless of AMVERIO_DOMAIN.

    export OPENAI_API_KEY=sk-...
    python3 test_jmgcargo_conversation.py
"""

import os
import json
from datetime import datetime
from openai import OpenAI
import domain

MODEL = os.environ.get("AMVERIO_MODEL", "gpt-4.1")
ACTIVE = domain.get_domain("jmgcargo")

_now = datetime.now()
SYSTEM_PROMPT = (
    f"Today's date is {_now.strftime('%A, %Y-%m-%d')}, current time {_now.strftime('%H:%M')}.\n\n"
    + ACTIVE["system_prompt_base"]
)

OPENAI_TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
    for t in ACTIVE["tool_schemas"]
]


def run_tool(name, tool_input):
    fn = ACTIVE["tool_functions"].get(name)
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
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    run_scenario(client, "Full quote to Sylhet, everything upfront", [
        "Hi, I want to send 2 boxes to Sylhet, Bangladesh, about 30kg total. Clothes and shoes. I'll drop them off. How much?",
        "Yes please send me a proper quote. Rahim Uddin, rahim@example.com",
        "Yes that's all correct",
    ])

    run_scenario(client, "Customer only knows box size (volumetric)", [
        "How much to send one big box to Dhaka? It's 60 x 50 x 50 cm and weighs about 10kg",
    ])

    run_scenario(client, "Prohibited items flagged", [
        "Sending 15kg to Chittagong - clothes, some perfumes and a power bank",
        "Ok I'll take out the perfume and power bank. Just clothes then.",
    ])

    run_scenario(client, "Collection with postcode", [
        "Can you collect 40kg from me in St Ives and send to Dhaka? Need insurance too.",
        "PE27 4LG. Name Sara Khan, sara.khan@example.com, 07700 900123. Contents are books and clothes. Yes go ahead.",
    ])

    run_scenario(client, "Customer insists power bank is fine", [
        "20kg to Dhaka, clothes and a small power bank. It's only a small one, that's fine right?",
    ])

    run_scenario(client, "Europe rate", [
        "What would 10kg to Paris cost?",
    ])

    run_scenario(client, "Banglish customer", [
        "Bhai 25kg Sylhet pathaite koto lagbe?",
    ])

    run_scenario(client, "Off-topic + tracking", [
        "Where's my parcel I sent last week? Also who won the football?",
    ])


if __name__ == "__main__":
    main()
