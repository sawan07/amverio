"""
Unit and integration test suite for the WhatsApp 24-hour customer service window
and Twilio Content API template message functionality.

Verifies:
1. Inbound messages update last_inbound_at in whatsapp_sessions.
2. Inside 24h window -> Free-form text dispatch succeeds.
3. Outside 24h window -> Free-form text is rejected with WhatsAppWindowError.
4. Outside 24h window -> Pre-approved template dispatch succeeds.
5. Unknown/missing template -> Rejected with WhatsAppTemplateError (no silent sends).
6. Phone number normalization (UK local, international, with/without whatsapp: prefix).
7. Booking reminder job correctly routes between free-text and template based on window.
8. Booking reminder job idempotency (does not duplicate reminders).
9. GET /api/whatsapp/sessions/{phone} diagnostic endpoint.
"""

import os
import sys
import time
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

import db
import whatsapp
import reminder_job
from app import app
from starlette.testclient import TestClient
from twilio.request_validator import RequestValidator


class TestWhatsApp24HourWindow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.mock_twilio = MagicMock()
        mock_msg = MagicMock()
        mock_msg.sid = "SM_mock_test_sid_12345"
        mock_msg.status = "queued"
        self.mock_twilio.messages.create.return_value = mock_msg

    def test_number_normalization(self):
        """Verifies UK and international numbers normalize into whatsapp:+E.164."""
        self.assertEqual(
            whatsapp.normalize_whatsapp_number("07123456789"),
            "whatsapp:+447123456789"
        )
        self.assertEqual(
            whatsapp.normalize_whatsapp_number("+44 7123 456789"),
            "whatsapp:+447123456789"
        )
        self.assertEqual(
            whatsapp.normalize_whatsapp_number("whatsapp:+447123456789"),
            "whatsapp:+447123456789"
        )
        self.assertEqual(
            whatsapp.normalize_whatsapp_number("+1 (415) 523-8886"),
            "whatsapp:+14155238886"
        )
        with self.assertRaises(ValueError):
            whatsapp.normalize_whatsapp_number("")

    def test_inbound_message_tracks_session_and_window(self):
        """Inbound webhook updates last_inbound_at and activates the 24h customer window."""
        phone = "whatsapp:+447888111222"
        # Seed or record inbound
        t0 = time.time()
        sess = db.record_whatsapp_inbound(phone, "Hello restaurant", timestamp=t0)
        self.assertEqual(sess["phone_number"], phone)
        self.assertEqual(sess["last_inbound_at"], t0)

        # Check inside window
        self.assertTrue(db.is_inside_24h_window(phone, now_ts=t0 + 100))
        # Check outside window (25 hours later)
        self.assertFalse(db.is_inside_24h_window(phone, now_ts=t0 + 25 * 3600))

    def test_inside_window_free_text_succeeds(self):
        """When customer is inside 24h window, sending free-form text succeeds."""
        phone = "whatsapp:+447888333444"
        now = time.time()
        # Record inbound 2 hours ago
        db.record_whatsapp_inbound(phone, "Hi", timestamp=now - 2 * 3600)

        res = whatsapp.send_whatsapp(
            to=phone,
            text="Your table is ready, see you shortly!",
            client=self.mock_twilio,
            now_ts=now,
        )

        self.assertEqual(res["type"], "text")
        self.assertEqual(res["to"], phone)
        self.mock_twilio.messages.create.assert_called_once()
        call_kwargs = self.mock_twilio.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["to"], phone)
        self.assertEqual(call_kwargs["body"], "Your table is ready, see you shortly!")

    def test_outside_window_free_text_rejected(self):
        """When customer is outside 24h window, free text raises WhatsAppWindowError."""
        phone = "whatsapp:+447888555666"
        now = time.time()
        # Record inbound 26 hours ago
        db.record_whatsapp_inbound(phone, "Old question", timestamp=now - 26 * 3600)

        with self.assertRaises(whatsapp.WhatsAppWindowError) as ctx:
            whatsapp.send_whatsapp(
                to=phone,
                text="Special discount tonight!",
                client=self.mock_twilio,
                now_ts=now,
            )

        self.assertIn("outside the 24-hour service window", str(ctx.exception))
        self.mock_twilio.messages.create.assert_not_called()

    def test_unknown_recipient_free_text_rejected(self):
        """Free-form text to unknown customer who never messaged is rejected."""
        unknown_phone = "whatsapp:+447000999888"
        with self.assertRaises(whatsapp.WhatsAppWindowError):
            whatsapp.send_whatsapp(
                to=unknown_phone,
                text="Cold contact message",
                client=self.mock_twilio,
            )
        self.mock_twilio.messages.create.assert_not_called()

    def test_outside_window_template_message_succeeds(self):
        """When customer is outside 24h window, pre-approved template message succeeds."""
        phone = "whatsapp:+447888777888"
        now = time.time()
        # Customer messaged 48 hours ago
        db.record_whatsapp_inbound(phone, "Hello", timestamp=now - 48 * 3600)

        vars_dict = {
            "1": "David Miller",
            "2": "2",
            "3": "20:30",
            "4": "The Copper Fork",
        }
        res = whatsapp.send_whatsapp(
            to=phone,
            template="booking_reminder",
            variables=vars_dict,
            client=self.mock_twilio,
            now_ts=now,
        )

        self.assertEqual(res["type"], "template")
        self.assertEqual(res["content_sid"], whatsapp.TEMPLATES["booking_reminder"]["content_sid"])
        self.mock_twilio.messages.create.assert_called_once()
        call_kwargs = self.mock_twilio.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["to"], phone)
        self.assertEqual(call_kwargs["content_sid"], whatsapp.TEMPLATES["booking_reminder"]["content_sid"])
        parsed_vars = json.loads(call_kwargs["content_variables"])
        self.assertEqual(parsed_vars["1"], "David Miller")
        self.assertEqual(parsed_vars["3"], "20:30")

    def test_unknown_template_rejected(self):
        """Unknown or unapproved template name raises WhatsAppTemplateError (no silent fail)."""
        phone = "whatsapp:+447888999000"
        with self.assertRaises(whatsapp.WhatsAppTemplateError) as ctx:
            whatsapp.send_whatsapp(
                to=phone,
                template="unregistered_holiday_promo",
                variables={"1": "Promo"},
                client=self.mock_twilio,
            )
        self.assertIn("Unknown WhatsApp template", str(ctx.exception))
        self.mock_twilio.messages.create.assert_not_called()

    def test_dry_run_mode(self):
        """Dry-run mode validates rules and previews output without calling Twilio."""
        phone = "whatsapp:+447111222999"
        res = whatsapp.send_whatsapp(
            to=phone,
            template="order_ready",
            variables={"1": "Sam", "2": "O0099", "3": "collection"},
            dry_run=True,
        )
        self.assertEqual(res["status"], "dry_run")
        self.assertEqual(res["type"], "template")
        self.assertIn("O0099", res["preview"])

    def test_booking_reminder_job_routing_and_idempotency(self):
        """Reminder job routes between free-text and template, and prevents duplicate reminders."""
        ref_dt = datetime(2026, 11, 15, 16, 0)
        due_time = "18:00"  # 2 hours ahead of 16:00
        due_date = "2026-11-15"

        # Customer 1: Inside 24h window
        phone_1 = "+447123000001"
        norm_1 = whatsapp.normalize_whatsapp_number(phone_1)
        db.record_whatsapp_inbound(norm_1, "I have a booking", timestamp=ref_dt.timestamp() - 3600)

        # Customer 2: Outside 24h window (booked 3 days ago, no recent message)
        phone_2 = "+447123000002"
        norm_2 = whatsapp.normalize_whatsapp_number(phone_2)
        db.record_whatsapp_inbound(norm_2, "Book me", timestamp=ref_dt.timestamp() - 72 * 3600)

        res_1 = {
            "id": "R_UNIT_001",
            "table_id": "T2",
            "date": due_date,
            "time": due_time,
            "party_size": 2,
            "name": "Alice Green",
            "phone": phone_1,
            "status": "CONFIRMED",
        }
        res_2 = {
            "id": "R_UNIT_002",
            "table_id": "T4",
            "date": due_date,
            "time": due_time,
            "party_size": 4,
            "name": "Bob Brown",
            "phone": phone_2,
            "status": "CONFIRMED",
        }

        db.add_reservation(res_1)
        db.add_reservation(res_2)

        try:
            # First run: should send 2 reminders
            results = reminder_job.run_booking_reminders(
                hours_ahead=3.0,
                now_dt=ref_dt,
                client=self.mock_twilio,
            )

            self.assertEqual(len(results), 2)
            res_dict = {r["reservation_id"]: r for r in results}

            # Check Alice (inside window) -> free text
            self.assertEqual(res_dict["R_UNIT_001"]["type"], "free_text")
            self.assertTrue(res_dict["R_UNIT_001"]["inside_window"])

            # Check Bob (outside window) -> template
            self.assertEqual(res_dict["R_UNIT_002"]["type"], "template")
            self.assertFalse(res_dict["R_UNIT_002"]["inside_window"])

            # Verify reminder_sent_at marked in DB
            db_res_1 = db.get_reservation("R_UNIT_001")
            db_res_2 = db.get_reservation("R_UNIT_002")
            self.assertIsNotNone(db_res_1.get("reminder_sent_at"))
            self.assertIsNotNone(db_res_2.get("reminder_sent_at"))

            # Second run: should send 0 reminders (idempotency)
            results_second_run = reminder_job.run_booking_reminders(
                hours_ahead=3.0,
                now_dt=ref_dt,
                client=self.mock_twilio,
            )
            self.assertEqual(len(results_second_run), 0)

        finally:
            # Clean up test rows
            import sqlite3
            conn = sqlite3.connect(db.SQLITE_DB_PATH)
            conn.execute("DELETE FROM reservations WHERE id IN ('R_UNIT_001', 'R_UNIT_002')")
            conn.commit()
            conn.close()

    def test_session_status_api_endpoint(self):
        """GET /api/whatsapp/sessions/{phone} returns session data and window boolean."""
        phone = "+447999123456"
        norm = whatsapp.normalize_whatsapp_number(phone)
        db.record_whatsapp_inbound(norm, "Testing status endpoint")

        resp = self.client.get(f"/api/whatsapp/sessions/{norm}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["exists"])
        self.assertTrue(data["inside_24h_window"])
        self.assertIsNotNone(data["last_inbound_at"])


if __name__ == "__main__":
    unittest.main()
