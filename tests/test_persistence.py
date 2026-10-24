"""
Persistence tests: bookings, orders, ID counters and conversation history must
survive a process restart, and concurrent requests must never double-book.

A "restart" is simulated by reloading the db module against the same SQLite
file (all in-process state is thrown away; only the file remains).
"""

import importlib
import os
import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import db
import tools
import chat

PHONE = "07123456789"


def _future_date(days: int = 3) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


class _PersistenceBase(unittest.TestCase):
    seed = "0"

    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in ("AMVERIO_DB_PATH", "AMVERIO_SEED_DEMO_DATA")}
        self.tmp = tempfile.mkdtemp(prefix="amverio-test-")
        self.db_file = os.path.join(self.tmp, "nested", "dir", "amverio.db")
        os.environ["AMVERIO_DB_PATH"] = self.db_file
        os.environ["AMVERIO_SEED_DEMO_DATA"] = self.seed
        chat.SESSIONS.clear()
        self.restart()

    def tearDown(self):
        chat.SESSIONS.clear()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(db)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def restart(self):
        """Throw away all in-process state; only the SQLite file survives."""
        importlib.reload(db)

    def book(self, time_str="19:00", party=8, name="Test Guest"):
        return tools.book_table(_future_date(), time_str, party, name, PHONE)


class TestDataSurvivesRestart(_PersistenceBase):

    def test_database_file_is_created_at_configured_path(self):
        self.assertEqual(db.SQLITE_DB_PATH, self.db_file)
        self.assertTrue(os.path.exists(self.db_file))

    def test_booking_survives_restart_and_still_blocks_the_table(self):
        result = self.book(party=8)
        self.assertTrue(result["success"], result)
        res_id = result["reservation_id"]

        self.restart()

        saved = db.get_reservation(res_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["name"], "Test Guest")
        self.assertEqual(saved["status"], "CONFIRMED")
        self.assertEqual(saved["table_id"], "T8")
        # Only T8 seats 8, so the same slot must now be unavailable.
        availability = tools.check_table_availability(_future_date(), "19:00", 8)
        self.assertFalse(availability["available"])

    def test_cancel_persists_and_frees_the_table(self):
        res_id = self.book(party=8)["reservation_id"]
        self.assertTrue(tools.cancel_reservation(res_id)["success"])

        self.restart()

        self.assertEqual(db.get_reservation(res_id)["status"], "CANCELLED")
        self.assertTrue(tools.check_table_availability(_future_date(), "19:00", 8)["available"])
        self.assertTrue(self.book(party=8)["success"])

    def test_order_survives_restart(self):
        order_id = db.get_next_order_id()
        db.add_order({
            "id": order_id,
            "items": [{"menu_id": "M1", "name": "Chargrilled Chicken Burger", "quantity": 2,
                       "unit_price": 13.5, "line_total": 27.0}],
            "order_type": "collection",
            "name": "Order Tester",
            "phone": PHONE,
            "email": "o@example.com",
            "status": "PENDING_PAYMENT",
            "total": 27.0,
        })
        db.update_order_status(order_id, "PAID")

        self.restart()

        order = db.get_order(order_id)
        self.assertEqual(order["status"], "PAID")
        self.assertEqual(order["total"], 27.0)
        self.assertEqual(order["items"][0]["quantity"], 2)

    def test_ids_keep_counting_after_restart(self):
        first = self.book("12:00", party=2)["reservation_id"]
        second = self.book("14:00", party=2)["reservation_id"]
        self.assertEqual((first, second), ("R0001", "R0002"))

        self.restart()

        self.assertEqual(self.book("16:00", party=2)["reservation_id"], "R0003")

    def test_whatsapp_window_survives_restart(self):
        now = time.time()
        db.record_whatsapp_inbound("whatsapp:+447123456789", "hi", timestamp=now - 3600)

        self.restart()

        self.assertTrue(db.is_inside_24h_window("whatsapp:+447123456789", now_ts=now))


class TestBookingRules(_PersistenceBase):

    def test_overlapping_slot_rejected_but_back_to_back_allowed(self):
        self.assertTrue(self.book("19:00", party=8)["success"])
        self.assertFalse(self.book("19:30", party=8)["success"])   # overlaps the 90-minute sitting
        self.assertTrue(self.book("20:30", party=8)["success"])    # starts exactly when the first ends

    def test_falls_back_to_next_table_that_fits(self):
        # Two 2-seat tables, then a bigger one is offered.
        first = self.book("19:00", party=2)
        second = self.book("19:00", party=2)
        third = self.book("19:00", party=2)
        self.assertTrue(first["success"] and second["success"] and third["success"])
        self.assertEqual({first["table_id"], second["table_id"]}, {"T1", "T2"})
        self.assertEqual(third["table_id"], "T3")


class TestConcurrency(_PersistenceBase):

    def test_simultaneous_requests_cannot_double_book(self):
        results, start = [], threading.Barrier(12)

        def attempt(i):
            start.wait()
            results.append(self.book("19:00", party=8, name=f"Guest {i}"))

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r.get("success")]
        self.assertEqual(len(results), 12)
        self.assertEqual(len(successes), 1, f"expected exactly one booking, got {len(successes)}")
        self.assertEqual(len(db.get_reservations()), 1)

    def test_simultaneous_id_requests_are_all_unique(self):
        ids, start = [], threading.Barrier(20)

        def grab():
            start.wait()
            ids.append(db.get_next_order_id())

        threads = [threading.Thread(target=grab) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(ids), 20)
        self.assertEqual(len(set(ids)), 20)


class TestDemoSeed(_PersistenceBase):

    def test_seed_can_be_switched_off(self):
        self.assertEqual(db.get_orders(), [])
        self.assertEqual(db.get_reservations(), [])

    def test_seed_runs_once_and_is_not_duplicated_on_restart(self):
        os.environ["AMVERIO_SEED_DEMO_DATA"] = "1"
        shutil.rmtree(os.path.dirname(self.db_file), ignore_errors=True)
        self.restart()
        self.assertEqual(len(db.get_orders()), 3)
        self.assertEqual(len(db.get_reservations()), 3)

        self.restart()

        self.assertEqual(len(db.get_orders()), 3)
        self.assertEqual(len(db.get_reservations()), 3)


class _FakeOpenAI:
    """Minimal stand-in for the OpenAI client: replies in plain text, records what it was sent."""

    def __init__(self, reply="Hello from the agent"):
        self.reply = reply
        self.seen = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, tools, messages):
        self.seen.append([dict(m) for m in messages])
        reply = self.reply

        class _Msg:
            tool_calls = None
            content = reply

            def model_dump(self, exclude_none=True):
                return {"role": "assistant", "content": reply}

        return SimpleNamespace(choices=[SimpleNamespace(message=_Msg())])


class TestConversationPersistence(_PersistenceBase):

    def test_conversation_continues_after_restart(self):
        client = _FakeOpenAI()
        chat.respond("wa-1", "I'd like a table for 4", domain_id="restaurant", client=client)

        chat.SESSIONS.clear()   # process "restarts": memory is gone
        self.restart()

        client2 = _FakeOpenAI("Sure, what time?")
        chat.respond("wa-1", "Tomorrow at 7", domain_id="restaurant", client=client2)

        sent = client2.seen[0]
        roles = [m["role"] for m in sent]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(sent[1]["content"], "I'd like a table for 4")
        self.assertEqual(sent[3]["content"], "Tomorrow at 7")

    def test_expired_conversation_is_not_restored(self):
        old = time.time() - chat.SESSION_TTL_SECONDS - 60
        db.save_conversation("wa-old", "restaurant",
                             [{"role": "system", "content": "x"}, {"role": "user", "content": "stale"}], old)

        session = chat._get_or_create_session("wa-old", "restaurant")

        self.assertEqual(len(session["messages"]), 1)   # fresh: just the system prompt

    def test_stale_rows_are_purged(self):
        now = time.time()
        db.save_conversation("fresh", "restaurant", [], now)
        db.save_conversation("stale", "restaurant", [], now - 10_000)

        removed = db.delete_stale_conversations(now - 5_000)

        self.assertEqual(removed, 1)
        self.assertIsNotNone(db.load_conversation("fresh"))
        self.assertIsNone(db.load_conversation("stale"))

    def test_storage_failure_never_breaks_a_reply(self):
        original = db.save_conversation
        db.save_conversation = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
        try:
            reply = chat.respond("wa-2", "hi", domain_id="restaurant", client=_FakeOpenAI("still works"))
        finally:
            db.save_conversation = original
        self.assertEqual(reply, "still works")


if __name__ == "__main__":
    unittest.main()
