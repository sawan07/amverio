"""
Tests for the direct Meta WhatsApp Cloud API integration (meta_whatsapp.py + the
/webhooks/meta/whatsapp routes in app.py + the WHATSAPP_PROVIDER switch in reminder_job.py).

Everything runs against fixtures: Meta's HTTP API is replaced by a fake, and the LLM is mocked.

Covers:
1. GET handshake (hub.mode / hub.verify_token / hub.challenge).
2. POST HMAC-SHA256 signature verification (X-Hub-Signature-256) - missing, forged, no secret.
3. Inbound parsing: text, button/interactive replies, media, delivery-status payloads.
4. Idempotency (Meta retries), 24-hour window tracking, session id format.
5. Outbound payloads sent to graph.facebook.com (text + template), Graph version/URL, bearer token.
6. 24-hour window rule, Meta error 131047, delivery errors, dry run, missing credentials.
7. Long replies are split; agent failures send a polite fallback.
8. reminder_job dispatching through Meta when WHATSAPP_PROVIDER=meta.
"""

import hashlib
import hmac
import json
import os
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
import chat
import db
import meta_whatsapp
import reminder_job
from whatsapp import WhatsAppWindowError, WhatsAppTemplateError, WhatsAppDeliveryError

APP_SECRET = "test_meta_app_secret_123"
VERIFY_TOKEN = "test_verify_token_abc"
PHONE_ID = "1055550001111"
ACCESS_TOKEN = "EAAtest_access_token"
ENV = {
    "META_APP_SECRET": APP_SECRET,
    "META_WA_VERIFY_TOKEN": VERIFY_TOKEN,
    "META_WA_PHONE_NUMBER_ID": PHONE_ID,
    "META_WA_ACCESS_TOKEN": ACCESS_TOKEN,
    "META_WA_BUSINESS_ACCOUNT_ID": "2055550002222",
}
ENV_KEYS = list(ENV) + ["META_GRAPH_API_VERSION", "META_WA_TEMPLATE_LANG", "WHATSAPP_PROVIDER"]


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {
            "messaging_product": "whatsapp",
            "contacts": [{"input": "x", "wa_id": "x"}],
            "messages": [{"id": "wamid.FAKE123"}],
        }

    def json(self):
        return self._body


class FakeHTTP:
    """Records every POST that would have gone to graph.facebook.com."""

    def __init__(self, response=None):
        self.calls = []
        self.response = response or FakeResponse()

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self.response


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def inbound_payload(wa_id="447700900101", text="Hi, table for 2 please", msg_id="wamid.IN001",
                    mtype="text", extra=None, ts=None):
    msg = {"from": wa_id, "id": msg_id, "timestamp": str(int(ts or time.time())), "type": mtype}
    if mtype == "text":
        msg["text"] = {"body": text}
    if extra:
        msg.update(extra)
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "2055550002222",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "15550001111", "phone_number_id": PHONE_ID},
                    "contacts": [{"profile": {"name": "Alex Morgan"}, "wa_id": wa_id}],
                    "messages": [msg],
                },
            }],
        }],
    }


class MetaEnvTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        os.environ.update(ENV)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestHandshake(MetaEnvTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app.app)

    def test_correct_token_echoes_challenge_as_plain_text(self):
        r = self.client.get("/webhooks/meta/whatsapp", params={
            "hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1158201444"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "1158201444")
        self.assertTrue(r.headers["content-type"].startswith("text/plain"))

    def test_wrong_token_rejected(self):
        r = self.client.get("/webhooks/meta/whatsapp", params={
            "hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})
        self.assertEqual(r.status_code, 403)

    def test_wrong_mode_rejected(self):
        r = self.client.get("/webhooks/meta/whatsapp", params={
            "hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1"})
        self.assertEqual(r.status_code, 403)

    def test_missing_params_rejected(self):
        self.assertEqual(self.client.get("/webhooks/meta/whatsapp").status_code, 403)

    def test_unconfigured_verify_token_rejects_everything(self):
        os.environ.pop("META_WA_VERIFY_TOKEN")
        r = self.client.get("/webhooks/meta/whatsapp", params={
            "hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"})
        self.assertEqual(r.status_code, 403)


class TestSignature(MetaEnvTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app.app)

    def _post(self, body: bytes, headers=None):
        return self.client.post("/webhooks/meta/whatsapp", content=body,
                                headers={"Content-Type": "application/json", **(headers or {})})

    def test_missing_signature_rejected(self):
        self.assertEqual(self._post(b"{}").status_code, 403)

    def test_forged_signature_rejected(self):
        body = json.dumps(inbound_payload()).encode()
        r = self._post(body, {"X-Hub-Signature-256": sign(body, secret="wrong_secret")})
        self.assertEqual(r.status_code, 403)

    def test_signature_over_different_body_rejected(self):
        body = json.dumps(inbound_payload()).encode()
        other = json.dumps(inbound_payload(text="tampered")).encode()
        self.assertEqual(self._post(body, {"X-Hub-Signature-256": sign(other)}).status_code, 403)

    def test_malformed_header_rejected(self):
        body = b"{}"
        digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertEqual(self._post(body, {"X-Hub-Signature-256": digest}).status_code, 403)  # no "sha256=" prefix

    def test_no_app_secret_configured_rejects_even_a_plausible_signature(self):
        os.environ.pop("META_APP_SECRET")
        body = b"{}"
        self.assertEqual(self._post(body, {"X-Hub-Signature-256": sign(body)}).status_code, 403)

    def test_valid_signature_accepted(self):
        body = b'{"object": "whatsapp_business_account", "entry": []}'
        r = self._post(body, {"X-Hub-Signature-256": sign(body)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["accepted"], 0)

    def test_valid_signature_but_invalid_json_is_400(self):
        body = b"not json"
        self.assertEqual(self._post(body, {"X-Hub-Signature-256": sign(body)}).status_code, 400)


class TestParseInbound(unittest.TestCase):
    def test_text_message(self):
        [m] = meta_whatsapp.parse_inbound(inbound_payload(text="  Hello  "))
        self.assertEqual((m["from"], m["name"], m["type"], m["text"], m["message_id"]),
                         ("447700900101", "Alex Morgan", "text", "Hello", "wamid.IN001"))

    def test_interactive_button_and_list_replies_become_text(self):
        btn = inbound_payload(mtype="interactive", msg_id="a",
                              extra={"interactive": {"type": "button_reply", "button_reply": {"id": "1", "title": "Yes, confirm"}}})
        lst = inbound_payload(mtype="interactive", msg_id="b",
                              extra={"interactive": {"type": "list_reply", "list_reply": {"id": "2", "title": "Friday 19:00"}}})
        self.assertEqual(meta_whatsapp.parse_inbound(btn)[0]["text"], "Yes, confirm")
        self.assertEqual(meta_whatsapp.parse_inbound(lst)[0]["text"], "Friday 19:00")

    def test_template_quick_reply_button_becomes_text(self):
        p = inbound_payload(mtype="button", extra={"button": {"payload": "x", "text": "Cancel booking"}})
        self.assertEqual(meta_whatsapp.parse_inbound(p)[0]["text"], "Cancel booking")

    def test_media_has_no_text(self):
        p = inbound_payload(mtype="image", extra={"image": {"id": "999", "mime_type": "image/jpeg"}})
        [m] = meta_whatsapp.parse_inbound(p)
        self.assertEqual((m["type"], m["text"]), ("image", ""))

    def test_status_updates_have_no_messages(self):
        p = {"entry": [{"changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "statuses": [{"id": "wamid.OUT1", "status": "delivered", "recipient_id": "447700900101"}]}}]}]}
        self.assertEqual(meta_whatsapp.parse_inbound(p), [])

    def test_garbage_is_tolerated(self):
        self.assertEqual(meta_whatsapp.parse_inbound({}), [])
        self.assertEqual(meta_whatsapp.parse_inbound({"entry": [{"changes": [{}]}]}), [])

    def test_inbound_timestamp_never_in_the_future(self):
        self.assertLessEqual(meta_whatsapp.inbound_timestamp(time.time() + 3600), time.time())


class TestInboundFlow(MetaEnvTestCase):
    """POST /webhooks/meta/whatsapp end to end, with the LLM mocked and Meta's API faked."""

    def setUp(self):
        super().setUp()
        self.client = TestClient(app.app)
        app._processed_message_sids.clear()
        chat.SESSIONS.clear()
        self.fake_http = FakeHTTP()
        patcher = patch("meta_whatsapp.httpx.post", side_effect=self.fake_http.post)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _send(self, payload):
        body = json.dumps(payload).encode()
        return self.client.post("/webhooks/meta/whatsapp", content=body,
                                headers={"Content-Type": "application/json", "X-Hub-Signature-256": sign(body)})

    def test_text_message_reaches_agent_and_reply_goes_out_via_graph_api(self):
        with patch.object(app.chat_engine, "respond", return_value="Sure! **What time** works for you?") as respond:
            r = self._send(inbound_payload(wa_id="447700900201", msg_id="wamid.A1"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok", "accepted": 1})

        respond.assert_called_once_with(session_id="whatsapp:+447700900201",
                                        user_text="Hi, table for 2 please", domain_id="restaurant")
        [call] = self.fake_http.calls
        self.assertEqual(call["url"], f"https://graph.facebook.com/{meta_whatsapp.DEFAULT_GRAPH_API_VERSION}/{PHONE_ID}/messages")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {ACCESS_TOKEN}")
        self.assertEqual(call["json"], {
            "messaging_product": "whatsapp", "recipient_type": "individual", "to": "447700900201",
            "type": "text", "text": {"preview_url": False, "body": "Sure! *What time* works for you?"},
        })

    def test_inbound_opens_the_24h_window_and_stores_the_session(self):
        with patch.object(app.chat_engine, "respond", return_value="ok"):
            self._send(inbound_payload(wa_id="447700900202", msg_id="wamid.A2"))
        self.assertTrue(db.is_inside_24h_window("whatsapp:+447700900202"))
        self.assertIsNotNone(db.get_whatsapp_session("whatsapp:+447700900202"))

    def test_duplicate_message_id_is_processed_once(self):
        payload = inbound_payload(wa_id="447700900203", msg_id="wamid.DUP")
        with patch.object(app.chat_engine, "respond", return_value="ok") as respond:
            first = self._send(payload)
            second = self._send(payload)
        self.assertEqual((first.json()["accepted"], second.json()["accepted"]), (1, 0))
        self.assertEqual(respond.call_count, 1)
        self.assertEqual(len(self.fake_http.calls), 1)

    def test_status_updates_are_acknowledged_without_replying(self):
        payload = {"entry": [{"changes": [{"field": "messages", "value": {
            "statuses": [{"id": "wamid.X", "status": "read", "recipient_id": "447700900204"}]}}]}]}
        with patch.object(app.chat_engine, "respond") as respond:
            r = self._send(payload)
        self.assertEqual((r.status_code, r.json()["accepted"]), (200, 0))
        respond.assert_not_called()
        self.assertEqual(self.fake_http.calls, [])

    def test_media_message_gets_a_polite_text_only_reply(self):
        payload = inbound_payload(wa_id="447700900205", msg_id="wamid.IMG", mtype="image",
                                  extra={"image": {"id": "1", "mime_type": "image/jpeg"}})
        with patch.object(app.chat_engine, "respond") as respond:
            self._send(payload)
        respond.assert_not_called()
        self.assertIn("only read text messages", self.fake_http.calls[0]["json"]["text"]["body"])

    def test_long_reply_is_split_into_several_messages(self):
        long_reply = "\n\n".join(f"Paragraph {i}. " + ("word " * 120) for i in range(6))
        with patch.object(app.chat_engine, "respond", return_value=long_reply):
            self._send(inbound_payload(wa_id="447700900206", msg_id="wamid.LONG"))
        self.assertGreater(len(self.fake_http.calls), 1)
        for call in self.fake_http.calls:
            self.assertLessEqual(len(call["json"]["text"]["body"]), meta_whatsapp.MAX_CHUNK_CHARS)

    def test_agent_failure_sends_a_fallback_and_still_returns_200(self):
        with patch.object(app.chat_engine, "respond", side_effect=RuntimeError("boom")):
            r = self._send(inbound_payload(wa_id="447700900207", msg_id="wamid.ERR"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("trouble", self.fake_http.calls[0]["json"]["text"]["body"])

    def test_meta_api_failure_does_not_break_the_webhook(self):
        self.fake_http.response = FakeResponse(500, {"error": {"message": "internal", "code": 2}})
        with patch.object(app.chat_engine, "respond", return_value="ok"):
            r = self._send(inbound_payload(wa_id="447700900208", msg_id="wamid.DOWN"))
        self.assertEqual(r.status_code, 200)

    def test_two_customers_get_separate_sessions(self):
        with patch.object(app.chat_engine, "respond", return_value="ok") as respond:
            self._send(inbound_payload(wa_id="447700900209", msg_id="wamid.S1"))
            self._send(inbound_payload(wa_id="447700900210", msg_id="wamid.S2"))
        sessions = {c.kwargs["session_id"] for c in respond.call_args_list}
        self.assertEqual(sessions, {"whatsapp:+447700900209", "whatsapp:+447700900210"})


class TestOutboundClient(MetaEnvTestCase):
    def setUp(self):
        super().setUp()
        self.http = FakeHTTP()
        self.phone = "07700900301"
        self.norm = "whatsapp:+447700900301"

    def _open_window(self, hours_ago=1.0):
        db.record_whatsapp_inbound(self.norm, "hi", timestamp=time.time() - hours_ago * 3600)

    def test_text_inside_window_is_sent(self):
        self._open_window(1)
        res = meta_whatsapp.send_whatsapp(self.phone, text="Hello!", http=self.http)
        self.assertEqual((res["status"], res["type"], res["sid"]), ("sent", "text", "wamid.FAKE123"))
        self.assertEqual(self.http.calls[0]["json"]["to"], "447700900301")

    def test_text_outside_window_is_refused_and_nothing_is_sent(self):
        self._open_window(30)
        with self.assertRaises(WhatsAppWindowError):
            meta_whatsapp.send_whatsapp(self.phone, text="Hello!", http=self.http)
        self.assertEqual(self.http.calls, [])

    def test_text_to_unknown_number_is_refused(self):
        with self.assertRaises(WhatsAppWindowError):
            meta_whatsapp.send_whatsapp("07700900399", text="Hello!", http=self.http)

    def test_template_is_allowed_outside_the_window_with_ordered_parameters(self):
        self._open_window(30)
        res = meta_whatsapp.send_whatsapp(
            self.phone, template="booking_reminder", http=self.http,
            variables={"4": "The Copper Fork", "1": "Sarah", "3": "19:00", "2": "4"})   # deliberately unordered
        tmpl = self.http.calls[0]["json"]
        self.assertEqual(tmpl["type"], "template")
        self.assertEqual(tmpl["template"]["name"], "booking_reminder")
        self.assertEqual(tmpl["template"]["language"], {"code": "en_GB"})
        self.assertEqual(
            [p["text"] for p in tmpl["template"]["components"][0]["parameters"]],
            ["Sarah", "4", "19:00", "The Copper Fork"])
        self.assertEqual(res["type"], "template")
        self.assertFalse(res["inside_window"])
        self.assertIn("Sarah", res["preview"])

    def test_template_language_can_be_overridden(self):
        os.environ["META_WA_TEMPLATE_LANG"] = "en_US"
        meta_whatsapp.send_whatsapp(self.phone, template="order_ready", http=self.http,
                                    variables={"1": "Sam", "2": "O0012", "3": "pickup"})
        self.assertEqual(self.http.calls[0]["json"]["template"]["language"]["code"], "en_US")

    def test_template_parameters_are_cleaned_of_newlines(self):
        meta_whatsapp.send_whatsapp(self.phone, template="order_ready", http=self.http,
                                    variables={"1": "Sam\nLee", "2": "O1", "3": "pickup"})
        params = self.http.calls[0]["json"]["template"]["components"][0]["parameters"]
        self.assertEqual(params[0]["text"], "Sam Lee")

    def test_unknown_template_and_missing_variable_are_rejected(self):
        with self.assertRaises(WhatsAppTemplateError):
            meta_whatsapp.send_whatsapp(self.phone, template="not_a_template", http=self.http)
        with self.assertRaises(WhatsAppTemplateError):
            meta_whatsapp.send_whatsapp(self.phone, template="booking_reminder", http=self.http, variables={"1": "x"})
        self.assertEqual(self.http.calls, [])

    def test_all_four_templates_build_valid_payloads(self):
        from whatsapp import TEMPLATES
        for name in ("booking_confirmation", "booking_reminder", "order_ready", "booking_cancelled"):
            self.assertIn(name, TEMPLATES)
            vars_ = {k: f"v{k}" for k in TEMPLATES[name]["variables"]}
            res = meta_whatsapp.send_whatsapp(self.phone, template=name, variables=vars_, dry_run=True)
            self.assertEqual(res["status"], "dry_run")

    def test_graph_version_is_configurable(self):
        os.environ["META_GRAPH_API_VERSION"] = "v99.0"
        self._open_window()
        meta_whatsapp.send_whatsapp(self.phone, text="x", http=self.http)
        self.assertIn("/v99.0/", self.http.calls[0]["url"])

    def test_meta_error_131047_is_reported_as_a_window_error(self):
        self._open_window()
        self.http.response = FakeResponse(400, {"error": {"message": "Re-engagement message", "code": 131047}})
        with self.assertRaises(WhatsAppWindowError):
            meta_whatsapp.send_whatsapp(self.phone, text="x", http=self.http)

    def test_other_meta_errors_become_delivery_errors_with_the_reason(self):
        self._open_window()
        self.http.response = FakeResponse(401, {"error": {"message": "Invalid OAuth access token.", "code": 190}})
        with self.assertRaises(WhatsAppDeliveryError) as ctx:
            meta_whatsapp.send_whatsapp(self.phone, text="x", http=self.http)
        self.assertIn("Invalid OAuth access token", str(ctx.exception))
        self.assertNotIn(ACCESS_TOKEN, str(ctx.exception))

    def test_network_failure_becomes_delivery_error(self):
        self._open_window()

        class Boom:
            def post(self, *a, **k):
                raise ConnectionError("no route")

        with self.assertRaises(WhatsAppDeliveryError):
            meta_whatsapp.send_whatsapp(self.phone, text="x", http=Boom())

    def test_missing_credentials_raise_a_clear_error(self):
        self._open_window()
        os.environ.pop("META_WA_ACCESS_TOKEN")
        with self.assertRaises(WhatsAppDeliveryError) as ctx:
            meta_whatsapp.send_whatsapp(self.phone, text="x", http=self.http)
        self.assertIn("META_WA_ACCESS_TOKEN", str(ctx.exception))
        self.assertFalse(meta_whatsapp.is_configured())

    def test_dry_run_calls_nothing(self):
        self._open_window()
        res = meta_whatsapp.send_whatsapp(self.phone, text="x", http=self.http, dry_run=True)
        self.assertEqual(res["status"], "dry_run")
        self.assertEqual(self.http.calls, [])

    def test_neither_text_nor_template_is_an_error(self):
        with self.assertRaises(ValueError):
            meta_whatsapp.send_whatsapp(self.phone, http=self.http)

    def test_sending_records_the_outbound_time(self):
        self._open_window()
        meta_whatsapp.send_whatsapp(self.phone, text="x", http=self.http)
        self.assertIsNotNone(db.get_whatsapp_session(self.norm)["last_outbound_at"])


class TestReminderJobViaMeta(MetaEnvTestCase):
    def setUp(self):
        super().setUp()
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        self.http = FakeHTTP()
        self.now = datetime.now().replace(second=0, microsecond=0)
        self.when = self.now + timedelta(hours=1)

    def _booking(self, rid, phone):
        db.add_reservation({
            "id": rid, "table_id": "T3", "date": self.when.strftime("%Y-%m-%d"), "time": self.when.strftime("%H:%M"),
            "party_size": 4, "name": "Priya", "phone": phone, "status": "CONFIRMED",
        })

    def test_inside_window_sends_text_through_meta(self):
        self._booking("R_META_001", "07700900401")
        db.record_whatsapp_inbound("whatsapp:+447700900401", "hi", timestamp=self.now.timestamp() - 3600)
        [res] = [r for r in reminder_job.run_booking_reminders(now_dt=self.now, client=self.http)
                 if r["reservation_id"] == "R_META_001"]
        self.assertEqual((res["status"], res["type"]), ("sent", "free_text"))
        mine = [c for c in self.http.calls if c["json"].get("to") == "447700900401"]
        self.assertEqual(len(mine), 1)
        self.assertIn("graph.facebook.com", mine[0]["url"])
        self.assertEqual(mine[0]["json"]["type"], "text")
        self.assertIsNotNone(db.get_reservation("R_META_001")["reminder_sent_at"])

    def test_outside_window_sends_template_through_meta(self):
        self._booking("R_META_002", "07700900402")
        [res] = [r for r in reminder_job.run_booking_reminders(now_dt=self.now, client=self.http)
                 if r["reservation_id"] == "R_META_002"]
        self.assertEqual((res["status"], res["type"]), ("sent", "template"))
        call = [c for c in self.http.calls if c["json"].get("to") == "447700900402"][0]["json"]
        self.assertEqual((call["type"], call["template"]["name"]), ("template", "booking_reminder"))

    def test_default_provider_is_still_twilio(self):
        os.environ.pop("WHATSAPP_PROVIDER")
        self._booking("R_META_003", "07700900403")
        results = reminder_job.run_booking_reminders(now_dt=self.now, dry_run=True)
        mine = [r for r in results if r["reservation_id"] == "R_META_003"][0]
        self.assertTrue(mine["dispatch"]["sid"].startswith("SM_mock"))   # Twilio dry-run id, not "wamid"


if __name__ == "__main__":
    unittest.main()
