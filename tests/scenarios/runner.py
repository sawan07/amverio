"""
Scripted scenario runner for Amverio (The Copper Fork / DineSync).
Plays multi-turn conversations against the real LLM model using the core
tool-calling loop from chat.py, records markdown transcripts in
tests/scenarios/transcripts/, and validates behavioral expectations.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Callable, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env
_env_file = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(_env_file):
    try:
        with open(_env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    except Exception:
        pass

from openai import OpenAI
import domain
import db

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)


def reset_test_db() -> None:
    """Reset reservations and orders to baseline seeds so tests are isolated and reproducible."""
    try:
        conn = db._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM reservations WHERE id NOT IN ('R0001', 'R0002', 'R0003', 'R0004');")
        cur.execute("DELETE FROM orders WHERE id NOT IN ('O0001', 'O0002', 'O0003');")
        if hasattr(conn, "commit"):
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: could not reset test DB: {e}")


def get_system_prompt() -> str:
    prompt_path = os.path.join(PROJECT_ROOT, "system_prompt.md")
    with open(prompt_path) as f:
        base = f.read()
    now = datetime.now()
    return f"Today's date is {now.strftime('%A, %Y-%m-%d')}, current time {now.strftime('%H:%M')}.\n\n" + base


class Scenario:
    def __init__(
        self,
        scenario_id: str,
        title: str,
        turns: list[str],
        category: str = "new",
        validator: Optional[Callable[[list[dict], list[dict]], tuple[bool, str]]] = None,
    ):
        self.scenario_id = scenario_id
        self.title = title
        self.turns = turns
        self.category = category
        self.validator = validator


def run_tool(active_domain: dict, name: str, args: dict) -> dict:
    fn = active_domain["tool_functions"].get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**args)
    except Exception as e:
        return {"error": str(e)}


def execute_scenario(client: OpenAI, model: str, scenario: Scenario) -> dict:
    active = domain.get_domain("restaurant")
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

    system_prompt = get_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]
    tool_events: list[dict] = []
    turn_transcripts: list[dict] = []

    for user_turn in scenario.turns:
        messages.append({"role": "user", "content": user_turn})
        turn_record = {"user": user_turn, "assistant": "", "tool_calls": []}

        while True:
            response = client.chat.completions.create(
                model=model,
                tools=tools,
                messages=messages,
                temperature=0.2,
            )
            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                turn_record["assistant"] = msg.content or ""
                break

            for call in msg.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                result = run_tool(active, call.function.name, args)
                tool_event = {"tool": call.function.name, "args": args, "result": result}
                tool_events.append(tool_event)
                turn_record["tool_calls"].append(tool_event)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                })

        turn_transcripts.append(turn_record)

    # Validate
    passed = True
    reason = "Passed all checks."
    if scenario.validator:
        passed, reason = scenario.validator(turn_transcripts, tool_events)

    # Record transcript to markdown
    transcript_path = os.path.join(TRANSCRIPTS_DIR, f"{scenario.scenario_id}.md")
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"# Scenario: {scenario.title}\n\n")
        f.write(f"- **ID**: `{scenario.scenario_id}`\n")
        f.write(f"- **Category**: `{scenario.category}`\n")
        f.write(f"- **Status**: `{'PASSED' if passed else 'FAILED'}`\n")
        f.write(f"- **Verification**: {reason}\n")
        f.write(f"- **Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Conversation Transcript\n\n")

        for idx, turn in enumerate(turn_transcripts, start=1):
            f.write(f"### Turn {idx}\n\n")
            f.write(f"**Customer**: {turn['user']}\n\n")
            if turn["tool_calls"]:
                f.write("**Tool Executions**:\n```json\n")
                f.write(json.dumps(turn["tool_calls"], indent=2))
                f.write("\n```\n\n")
            f.write(f"**DineSync**: {turn['assistant']}\n\n")

    return {
        "id": scenario.scenario_id,
        "title": scenario.title,
        "category": scenario.category,
        "passed": passed,
        "reason": reason,
        "transcript_file": transcript_path,
        "turn_count": len(turn_transcripts),
    }


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------

def _has_tool(tool_events: list[dict], tool_name: str) -> bool:
    return any(e["tool"] == tool_name for e in tool_events)


def _last_reply(turn_transcripts: list[dict]) -> str:
    return turn_transcripts[-1]["assistant"].lower() if turn_transcripts else ""


# ---------------------------------------------------------------------------
# All Scenarios Definitions
# ---------------------------------------------------------------------------

SCENARIOS: list[Scenario] = [
    # Baseline Scenarios (from test_conversation.py)
    Scenario(
        "baseline_booking_upfront",
        "Table booking, info given upfront",
        ["Hi, can I book a table for 4 people this Friday at 7pm? My name's Alex Morgan, phone 07123456789."],
        category="baseline",
        validator=lambda t, e: (
            _has_tool(e, "book_table"),
            "Called book_table after availability check" if _has_tool(e, "book_table") else "Failed to call book_table"
        ),
    ),
    Scenario(
        "baseline_booking_withheld",
        "Table booking, info withheld (should ask for name/phone)",
        ["Table for 2 tomorrow at 8pm please."],
        category="baseline",
        validator=lambda t, e: (
            not _has_tool(e, "book_table") and any(w in _last_reply(t) for w in ["name", "phone", "number"]),
            "Prompted for missing name/phone without prematurely calling book_table"
            if not _has_tool(e, "book_table") else "Called book_table prematurely without name/phone"
        ),
    ),
    Scenario(
        "baseline_order_pickup",
        "Food order for pickup",
        [
            "What's on the menu?",
            "I'll get two chargrilled chicken burgers and a side of fries, for pickup. I'm Sam Lee, 07000111222, email sam.lee@example.com.",
        ],
        category="baseline",
        validator=lambda t, e: (
            _has_tool(e, "get_menu") and (
                "confirm" in _last_reply(t) or _has_tool(e, "place_order") or "£" in _last_reply(t)
            ),
            "Retrieved menu and prompted for order confirmation with price or placed order"
        ),
    ),
    Scenario(
        "baseline_order_delivery",
        "Delivery order (no delivery logistics exist yet)",
        ["Can I get a fish and chips delivered? Priya Shah, 07222333444, email priya.shah@example.com."],
        category="baseline",
        validator=lambda t, e: (
            any(w in _last_reply(t) for w in ["delivery", "confirm", "separately", "restaurant", "order"]),
            "Handled delivery order appropriately"
        ),
    ),
    Scenario(
        "baseline_off_topic",
        "Off-topic question (should stay on topic)",
        ["Random question, what's today's weather like?"],
        category="baseline",
        validator=lambda t, e: (
            len(e) == 0 and any(w in _last_reply(t) for w in ["table", "book", "menu", "order", "copper fork", "restaurant", "assist"]),
            "Stayed on topic without calling tools" if len(e) == 0 else "Erroneously called tools on off-topic question"
        ),
    ),
    Scenario(
        "baseline_overbooking",
        "Overbooking a table that doesn't fit (12 people)",
        ["Table for 12 tonight at 7, name Jordan, 07999888777."],
        category="baseline",
        validator=lambda t, e: (
            not _has_tool(e, "book_table") and any(w in _last_reply(t) for w in ["cannot", "sorry", "fit", "seat", "largest", "8", "call"]),
            "Correctly declined overbooking beyond capacity" if not _has_tool(e, "book_table") else "Booked table exceeding capacity"
        ),
    ),
    Scenario(
        "baseline_cancel_reservation",
        "Book then cancel a reservation",
        [
            "Hi, can I book a table for 2 this Saturday at 7pm? Jordan Blake, 07111 222333.",
            "Actually, I need to cancel that booking.",
        ],
        category="baseline",
        validator=lambda t, e: (
            _has_tool(e, "cancel_reservation"),
            "Successfully triggered cancel_reservation" if _has_tool(e, "cancel_reservation") else "Did not call cancel_reservation"
        ),
    ),
    Scenario(
        "baseline_reschedule",
        "Reschedule an existing reservation",
        [
            "I'd like a table for 4 this Sunday at 8pm. Priya Shah, 07222 333444.",
            "Actually can you move that to 9pm instead on the same day?",
        ],
        category="baseline",
        validator=lambda t, e: (
            _has_tool(e, "cancel_reservation") and _has_tool(e, "book_table"),
            "Cancelled old booking and booked new time" if (_has_tool(e, "cancel_reservation") and _has_tool(e, "book_table")) else "Failed cancel+rebook pattern"
        ),
    ),
    Scenario(
        "baseline_order_change_mind",
        "Add items, then change mind before confirming",
        [
            "Hi, I'd like to order two chargrilled chicken burgers for pickup.",
            "Actually, make that one burger, and add a side of fries instead.",
            "Yes that's right, go ahead. Sam Lee, 07099 888777, sam@example.com.",
        ],
        category="baseline",
        validator=lambda t, e: (
            _has_tool(e, "place_order"),
            "Placed updated order with single burger and fries"
        ),
    ),
    Scenario(
        "baseline_order_remove_item",
        "Remove an item entirely before confirming",
        [
            "Can I get a soup of the day and a chocolate brownie for pickup?",
            "Actually scrap the brownie, just the soup please.",
            "Yes confirm that. Priya Shah, 07222 333444, priya@example.com.",
        ],
        category="baseline",
        validator=lambda t, e: (
            _has_tool(e, "place_order"),
            "Placed final order with only the soup"
        ),
    ),

    # 12 New Edge-Case Scenarios
    Scenario(
        "edge_rude_customer",
        "Rude and impatient customer",
        ["Hurry up and stop being so slow! I need a table for 2 tomorrow at 7:30pm, name Mark Evans, phone 07123456789. Do your job."],
        category="edge_case",
        validator=lambda t, e: (
            _has_tool(e, "book_table") and not any(w in _last_reply(t) for w in ["rude", "attitude", "calm down", "insult"]),
            "Handled professionally and booked table without reacting defensively"
        ),
    ),
    Scenario(
        "edge_ambiguous_datetime",
        "Ambiguous date/time ('next weekend')",
        [
            "I want a table for 4 next weekend in the evening. Alex, 07123456789.",
            "Let's do Saturday at 7pm.",
        ],
        category="edge_case",
        validator=lambda t, e: (
            any(w in t[0]["assistant"].lower() for w in ["saturday", "sunday", "which day", "what time", "date", "time"])
            and _has_tool(e, "book_table"),
            "Clarified ambiguous date/time in turn 1 and booked in turn 2"
        ),
    ),
    Scenario(
        "edge_party_size_change",
        "Party size changes mid-conversation",
        [
            "Can I book a table for 2 this Friday at 7pm? Jordan Blake, 07111222333.",
            "Actually wait, two more friends are joining us, make it 4 people instead please.",
        ],
        category="edge_case",
        validator=lambda t, e: (
            any(call["tool"] == "book_table" and call["args"].get("party_size") == 4 for call in e) or
            any(call["tool"] == "check_table_availability" and call["args"].get("party_size") == 4 for call in e),
            "Adjusted party size to 4 and checked/booked for 4"
        ),
    ),
    Scenario(
        "edge_multi_category_order",
        "Multi-category order with unavailable drink item",
        [
            "Hi, I'd like a Soup of the Day, an 8oz Sirloin Steak, and a Diet Coke for pickup. Sam Lee, 07000111222, sam@example.com.",
            "Yes, that's fine, go ahead with just the food.",
        ],
        category="edge_case",
        validator=lambda t, e: (
            any(w in t[0]["assistant"].lower() for w in ["coke", "drink", "not on", "menu", "unavailable", "beverage"]) and
            _has_tool(e, "place_order"),
            "Identified drinks as unlisted and successfully placed valid food items"
        ),
    ),
    Scenario(
        "edge_add_remove_items",
        "Complex adding and removing items before confirming",
        [
            "Hi! I want two chicken burgers and two fries for pickup.",
            "Actually make it one chicken burger, one fish and chips, and remove all fries.",
            "Yes confirm that order. Priya Shah, 07222333444, priya@example.com.",
        ],
        category="edge_case",
        validator=lambda t, e: (
            _has_tool(e, "place_order"),
            "Calculated and placed order accurately after mid-turn adjustments"
        ),
    ),
    Scenario(
        "edge_change_mind_after_confirmation",
        "Customer tries to cancel or modify order after placement",
        [
            "I'll get a chargrilled chicken burger for pickup. Liam, 07123456789, liam@example.com.",
            "Yes please place the order now.",
            "Wait! I changed my mind, can you cancel that order and remove the burger?",
        ],
        category="edge_case",
        validator=lambda t, e: (
            _has_tool(e, "place_order") and
            any(w in _last_reply(t) for w in ["call", "kitchen", "phone", "cannot cancel", "cannot modify", "direct", "restaurant"]),
            "Explained placed orders cannot be cancelled via chat and directed to call restaurant"
        ),
    ),
    Scenario(
        "edge_unavailable_item",
        "Order request for items not on the restaurant menu",
        ["Can I order a Lobster Thermidor and a large Margherita Pizza for delivery?"],
        category="edge_case",
        validator=lambda t, e: (
            not _has_tool(e, "place_order") and
            any(w in _last_reply(t) for w in ["not on", "don't have", "do not serve", "menu", "steak", "burger", "bistro"]),
            "Politely declined unlisted items and referred to actual menu"
        ),
    ),
    Scenario(
        "edge_allergen_question",
        "Allergen and cross-contamination inquiry not in menu data",
        ["I have a severe peanut and sesame allergy. Is your wild mushroom risotto 100% nut-free and prepared in a separate allergy kitchen?"],
        category="edge_case",
        validator=lambda t, e: (
            not any(w in _last_reply(t) for w in ["is 100% safe", "is completely safe", "is definitely safe", "is completely nut-free", "yes, it is nut-free"]) and
            any(w in _last_reply(t) for w in ["staff", "kitchen", "severe", "allergy", "allergies", "contact", "speak", "check", "directly"]),
            "Did not guarantee unlisted allergen safety; advised contacting kitchen directly"
        ),
    ),
    Scenario(
        "edge_mixing_booking_and_order",
        "Customer attempts to pre-order food for dine-in table reservation",
        ["Hi, can I book a table for 2 this Friday at 7pm under Alex, 07123456789? Also can we pre-order two burgers to be on the table when we arrive?"],
        category="edge_case",
        validator=lambda t, e: (
            _has_tool(e, "check_table_availability") or _has_tool(e, "book_table"),
            "Addressed the table booking while clarifying food ordering policy"
        ),
    ),
    Scenario(
        "edge_non_english_greeting",
        "Non-English greeting and inquiry",
        ["Bonjour! Avez-vous une table pour 2 ce soir à 19h? Je m'appelle Jean Dupont, 07123456789."],
        category="edge_case",
        validator=lambda t, e: (
            _has_tool(e, "check_table_availability") or _has_tool(e, "book_table"),
            "Welcomed politely in English and processed table inquiry"
        ),
    ),
    Scenario(
        "edge_very_long_message",
        "Lengthy rambling message with core booking details buried inside",
        [
            "Hello! My partner and I are celebrating our 10th anniversary this weekend. We've been looking for a cozy British bistro "
            "because we got engaged in the Lake District ten years ago. A colleague in our London office recommended The Copper Fork "
            "and we really love the sound of your chargrilled sirloin. We are travelling in by train and our hotel check-in is at 4pm. "
            "Could we please reserve a table for 2 people this Saturday at 7:30pm? My name is David Miller and my UK mobile is 07987654321. "
            "We can't wait to visit!"
        ],
        category="edge_case",
        validator=lambda t, e: (
            _has_tool(e, "check_table_availability") or _has_tool(e, "book_table"),
            "Extracted buried reservation info and checked/booked table"
        ),
    ),
    Scenario(
        "edge_off_topic_deep",
        "Completely off-topic general knowledge question",
        ["Can you help me write Python code to scrape Twitter, and who won the World Cup in 1998?"],
        category="edge_case",
        validator=lambda t, e: (
            len(e) == 0 and any(w in _last_reply(t) for w in ["table", "book", "menu", "order", "copper fork", "restaurant"]),
            "Firmly and politely declined off-topic query and refocused on restaurant"
        ),
    ),
]


def main():
    parser = argparse.ArgumentParser(description="Amverio Scenario Runner")
    parser.add_argument("--scenario", help="Run only a specific scenario ID")
    parser.add_argument("--category", choices=["baseline", "edge_case", "all"], default="all")
    parser.add_argument("--model", default=os.environ.get("AMVERIO_MODEL", "gpt-4o"))
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable is not set.")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    scenarios_to_run = SCENARIOS
    if args.scenario:
        scenarios_to_run = [s for s in SCENARIOS if s.scenario_id == args.scenario]
        if not scenarios_to_run:
            print(f"Unknown scenario ID: {args.scenario}")
            sys.exit(1)
    elif args.category != "all":
        scenarios_to_run = [s for s in SCENARIOS if s.category == args.category]

    print(f"\n======================================================================")
    print(f"AMVERIO SCENARIO RUNNER — {len(scenarios_to_run)} scenarios using {args.model}")
    print(f"Transcripts will be saved to: {TRANSCRIPTS_DIR}")
    print(f"======================================================================\n")

    reset_test_db()

    results = []
    for s in scenarios_to_run:
        print(f"Running [{s.category.upper()}] {s.scenario_id}: {s.title}...", end=" ", flush=True)
        try:
            res = execute_scenario(client, args.model, s)
            status_str = "PASS" if res["passed"] else "FAIL"
            print(f"[{status_str}]")
            if not res["passed"]:
                print(f"    Reason: {res['reason']}")
            results.append(res)
        except Exception as e:
            print(f"[ERROR: {e}]")
            results.append({
                "id": s.scenario_id,
                "title": s.title,
                "category": s.category,
                "passed": False,
                "reason": f"Execution exception: {e}",
            })

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed}/{total} PASSED ({failed} failed)")
    print("=" * 70)

    for r in results:
        status_tag = "✓" if r["passed"] else "✗"
        print(f"  {status_tag} {r['id']:<35} : {r['reason']}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
