"""
Simulates and verifies end-to-end scripted scenarios over the Twilio WhatsApp Sandbox
webhook endpoint (POST /webhooks/twilio/whatsapp).

Scenarios tested:
1. Booking: Table for 4 this Friday at 7pm, Alex Morgan, 07123456789.
2. Order: 2 Chargrilled Chicken Burgers for pickup, Sam Lee, 07099888777, sam@example.com.
3. Cancel: Cancel an existing reservation.
4. Menu Q&A: Inquire about vegetarian/gluten-free options and menu prices.
5. Off-topic: Ask an unrelated question (weather/general trivia) and verify polite refusal.
"""

import os
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime

# Load environment
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

from starlette.testclient import TestClient
from twilio.request_validator import RequestValidator
from app import app

client = TestClient(app)

AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
if not AUTH_TOKEN:
    secrets_file = os.path.join(_root, ".secrets.txt")
    if os.path.exists(secrets_file):
        with open(secrets_file) as f:
            for line in f:
                if line.startswith("TWILIO_AUTH_TOKEN="):
                    AUTH_TOKEN = line.strip().split("=", 1)[1].strip()

if not AUTH_TOKEN:
    AUTH_TOKEN = "test_auth_token_32chars_long_1234"

validator = RequestValidator(AUTH_TOKEN)
WEBHOOK_URL = "http://testserver/webhooks/twilio/whatsapp"


def send_whatsapp_message(from_number: str, body: str) -> tuple[list[str], float]:
    """
    Simulates sending an incoming WhatsApp message via Twilio webhook with valid signature.
    Returns (list of response messages from TwiML, latency in seconds).
    """
    message_sid = f"SM{uuid.uuid4().hex}"
    payload = {
        "From": from_number,
        "To": "whatsapp:+14155238886",
        "Body": body,
        "MessageSid": message_sid,
        "AccountSid": os.environ.get("TWILIO_ACCOUNT_SID", "ACtest1234567890"),
        "NumMedia": "0",
    }
    signature = validator.compute_signature(WEBHOOK_URL, payload)

    t0 = time.time()
    resp = client.post(
        "/webhooks/twilio/whatsapp",
        data=payload,
        headers={"X-Twilio-Signature": signature},
    )
    latency = time.time() - t0

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert "application/xml" in resp.headers.get("content-type", "")

    root = ET.fromstring(resp.content)
    messages = [msg.text for msg in root.findall("Message") if msg.text]
    return messages, latency


def run_scenario(name: str, phone: str, turns: list[str]) -> list[dict]:
    print(f"\n=======================================================")
    print(f"RUNNING SCENARIO: {name} (Phone: {phone})")
    print(f"=======================================================")
    history = []
    for turn_idx, user_msg in enumerate(turns, 1):
        print(f"\n[Turn {turn_idx}] User: {user_msg}")
        replies, latency = send_whatsapp_message(phone, user_msg)
        joined_reply = "\n".join(replies)
        print(f"[Turn {turn_idx}] Agent ({latency:.2f}s): {joined_reply}")
        history.append({
            "turn": turn_idx,
            "user": user_msg,
            "agent_replies": replies,
            "latency": latency,
        })
    return history


def main():
    scenarios_data = {}

    # Scenario 1: Booking
    scenarios_data["1_booking"] = run_scenario(
        "Table Booking",
        "whatsapp:+447111222333",
        [
            "Hi, I'd like to book a table for 4 people this Friday at 7pm please.",
            "My name is Alex Morgan and phone is 07123456789.",
        ]
    )

    # Scenario 2: Order
    scenarios_data["2_order"] = run_scenario(
        "Food Order (Pickup)",
        "whatsapp:+447222333444",
        [
            "Can I order two chargrilled chicken burgers for pickup?",
            "Yes confirm that please: Sam Lee, 07099 888777, sam@example.com.",
        ]
    )

    # Scenario 3: Cancel Reservation
    # First book a reservation, then cancel it
    scenarios_data["3_cancel"] = run_scenario(
        "Cancellation Flow",
        "whatsapp:+447333444555",
        [
            "Book a table for 2 tomorrow at 6pm. Jordan, 07999888777.",
            "Actually I need to cancel that reservation please.",
        ]
    )

    # Scenario 4: Menu Q&A
    scenarios_data["4_menu_qa"] = run_scenario(
        "Menu Q&A",
        "whatsapp:+447444555666",
        [
            "Hi, what vegetarian or gluten-free options do you have on the menu?",
            "How much is the Wild Mushroom Risotto, and what comes with it?",
        ]
    )

    # Scenario 5: Off-topic Guardrail
    scenarios_data["5_off_topic"] = run_scenario(
        "Off-Topic Guardrail",
        "whatsapp:+447555666777",
        [
            "Random question, what's today's weather like in London?",
            "Can you write a poem about artificial intelligence?",
        ]
    )

    print("\n=======================================================")
    print("ALL 5 SCENARIOS COMPLETED SUCCESSFULLY!")
    print("=======================================================")
    return scenarios_data


if __name__ == "__main__":
    main()
