"""
Unit and integration tests for the Twilio WhatsApp webhook endpoint in app.py.

Verifies:
1. Rejection of requests with invalid or missing X-Twilio-Signature with HTTP 403.
2. Acceptance and proper processing of validly signed Twilio webhook requests.
3. Polite handling of media-only and empty incoming messages.
4. Idempotent processing of duplicate MessageSid values (no double processing).
5. Automatic splitting of long messages (> 1600 characters) into multiple TwiML <Message> chunks.
6. Per-phone-number session tracking through chat.respond().
7. Mocked signature validator and mocked LLM testing.
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator
import xml.etree.ElementTree as ET

# Ensure dummy auth token for tests if not set
TEST_AUTH_TOKEN = "test_auth_token_secret_12345"
os.environ["TWILIO_AUTH_TOKEN"] = TEST_AUTH_TOKEN
os.environ["TWILIO_WEBHOOK_URL"] = "http://testserver/webhooks/twilio/whatsapp"

import app
import chat


class TestTwilioWhatsAppWebhook(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.validator = RequestValidator(TEST_AUTH_TOKEN)
        self.webhook_url = "http://testserver/webhooks/twilio/whatsapp"
        app._processed_message_sids.clear()
        chat.SESSIONS.clear()

    def _sign_payload(self, params: dict, url: str = None) -> dict:
        target_url = url or self.webhook_url
        sig = self.validator.compute_signature(target_url, params)
        return {"X-Twilio-Signature": sig}

    def test_info_endpoint_get(self):
        """GET /webhooks/twilio/whatsapp returns status info."""
        resp = self.client.get("/webhooks/twilio/whatsapp")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ready")

    def test_missing_signature_rejected(self):
        """Requests without X-Twilio-Signature header are rejected with 403."""
        payload = {
            "From": "whatsapp:+447123456789",
            "Body": "Hello",
            "MessageSid": "SM_test_001",
        }
        resp = self.client.post("/webhooks/twilio/whatsapp", data=payload)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Invalid Twilio signature", resp.text)

    def test_invalid_signature_rejected(self):
        """Requests with forged/invalid X-Twilio-Signature are rejected with 403."""
        payload = {
            "From": "whatsapp:+447123456789",
            "Body": "Hello",
            "MessageSid": "SM_test_002",
        }
        headers = {"X-Twilio-Signature": "invalid_forged_signature"}
        resp = self.client.post("/webhooks/twilio/whatsapp", data=payload, headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Invalid Twilio signature", resp.text)

    @patch("app.chat_engine.respond")
    def test_valid_request_calls_respond_and_returns_twiml(self, mock_respond):
        """Validly signed request invokes chat.respond and formats TwiML <Response><Message>."""
        mock_respond.return_value = "Welcome to The Copper Fork! We have tables for 2 and 4 available tonight."
        payload = {
            "From": "whatsapp:+447123456789",
            "Body": "Hi, do you have a table tonight?",
            "MessageSid": "SM_test_003",
        }
        headers = self._sign_payload(payload)

        resp = self.client.post("/webhooks/twilio/whatsapp", data=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/xml")

        mock_respond.assert_called_once_with(
            session_id="whatsapp:+447123456789",
            user_text="Hi, do you have a table tonight?",
            domain_id="restaurant",
        )

        root = ET.fromstring(resp.content)
        self.assertEqual(root.tag, "Response")
        messages = root.findall("Message")
        self.assertEqual(len(messages), 1)
        self.assertIn("Welcome to The Copper Fork", messages[0].text)

    @patch("app.chat_engine.respond")
    def test_idempotency_duplicate_message_sid_ignored(self, mock_respond):
        """Duplicate MessageSid is acknowledged with empty TwiML without calling agent again."""
        mock_respond.return_value = "Order confirmed!"
        payload = {
            "From": "whatsapp:+447123456789",
            "Body": "Can I order 1 chicken burger?",
            "MessageSid": "SM_idempotency_001",
        }
        headers = self._sign_payload(payload)

        # First request
        resp1 = self.client.post("/webhooks/twilio/whatsapp", data=payload, headers=headers)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(mock_respond.call_count, 1)

        # Re-delivery of identical MessageSid
        resp2 = self.client.post("/webhooks/twilio/whatsapp", data=payload, headers=headers)
        self.assertEqual(resp2.status_code, 200)
        # Agent should NOT be called again
        self.assertEqual(mock_respond.call_count, 1)

        root = ET.fromstring(resp2.content)
        self.assertEqual(root.tag, "Response")
        self.assertEqual(len(root.findall("Message")), 0)

    def test_media_only_message_handling(self):
        """Media-only messages without body are handled with polite text prompt."""
        payload = {
            "From": "whatsapp:+447123456789",
            "Body": "",
            "NumMedia": "1",
            "MessageSid": "SM_media_001",
        }
        headers = self._sign_payload(payload)

        resp = self.client.post("/webhooks/twilio/whatsapp", data=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        root = ET.fromstring(resp.content)
        messages = root.findall("Message")
        self.assertEqual(len(messages), 1)
        self.assertIn("can only read text messages", messages[0].text)

    def test_empty_message_handling(self):
        """Completely empty message returns friendly welcome prompt."""
        payload = {
            "From": "whatsapp:+447123456789",
            "Body": "",
            "NumMedia": "0",
            "MessageSid": "SM_empty_001",
        }
        headers = self._sign_payload(payload)

        resp = self.client.post("/webhooks/twilio/whatsapp", data=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        root = ET.fromstring(resp.content)
        messages = root.findall("Message")
        self.assertEqual(len(messages), 1)
        self.assertIn("Welcome to The Copper Fork", messages[0].text)

    @patch("app.chat_engine.respond")
    def test_long_message_splitting(self, mock_respond):
        """Messages > 1600 characters are split into multiple <Message> chunks <= 1600 chars."""
        # Generate a 2500 character response with distinct paragraphs
        para1 = "Paragraph 1: " + ("Our starters include fresh daily soups and stone-baked garlic flatbreads. " * 15)
        para2 = "Paragraph 2: " + ("Our main courses feature prime dry-aged sirloin steaks and burgers. " * 15)
        long_reply = f"{para1}\n\n{para2}"
        self.assertGreater(len(long_reply), 2000)
        mock_respond.return_value = long_reply

        payload = {
            "From": "whatsapp:+447123456789",
            "Body": "Tell me all about everything on your menu in detail",
            "MessageSid": "SM_long_001",
        }
        headers = self._sign_payload(payload)

        resp = self.client.post("/webhooks/twilio/whatsapp", data=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        root = ET.fromstring(resp.content)
        messages = root.findall("Message")

        # Must be split into at least 2 messages
        self.assertGreaterEqual(len(messages), 2)
        for msg in messages:
            # Twilio's WhatsApp hard limit is 1600
            self.assertLessEqual(len(msg.text), 1600)

    @patch("app.chat_engine.respond")
    def test_session_continuity_by_phone_number(self, mock_respond):
        """Consecutive messages with same From number pass the same session_id."""
        mock_respond.side_effect = ["Reply 1", "Reply 2"]
        phone = "whatsapp:+447999888777"

        p1 = {"From": phone, "Body": "First turn", "MessageSid": "SM_sess_1"}
        self.client.post("/webhooks/twilio/whatsapp", data=p1, headers=self._sign_payload(p1))

        p2 = {"From": phone, "Body": "Second turn", "MessageSid": "SM_sess_2"}
        self.client.post("/webhooks/twilio/whatsapp", data=p2, headers=self._sign_payload(p2))

        self.assertEqual(mock_respond.call_count, 2)
        # Verify same session_id was passed on both calls
        calls = mock_respond.call_args_list
        self.assertEqual(calls[0].kwargs["session_id"], phone)
        self.assertEqual(calls[1].kwargs["session_id"], phone)

    def test_real_agent_turn_end_to_end(self):
        """End-to-end integration test with the real model through the signed webhook."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            self.skipTest("OPENAI_API_KEY not configured")

        phone = "whatsapp:+447000123456"
        payload = {
            "From": phone,
            "Body": "What starters do you have on the menu?",
            "MessageSid": "SM_e2e_live_001",
        }
        headers = self._sign_payload(payload)

        resp = self.client.post("/webhooks/twilio/whatsapp", data=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/xml")

        root = ET.fromstring(resp.content)
        messages = root.findall("Message")
        self.assertGreaterEqual(len(messages), 1)
        full_reply = " ".join(m.text for m in messages if m.text)
        self.assertTrue(
            any(w in full_reply.lower() for w in ["soup", "flatbread", "starter"]),
            f"Unexpected reply content: {full_reply}"
        )

    def test_whatsapp_formatting_adapter(self):
        """Verify markdown formatting is adapted for WhatsApp (e.g. **bold** -> *bold*)."""
        from app import _format_for_whatsapp
        raw = "Here is **bold text** and [Link Name](https://example.com) with ### Header Title"
        formatted = _format_for_whatsapp(raw)
        self.assertIn("*bold text*", formatted)
        self.assertNotIn("**bold text**", formatted)
        self.assertIn("Link Name: https://example.com", formatted)
        self.assertIn("*Header Title*", formatted)


if __name__ == "__main__":
    unittest.main()

