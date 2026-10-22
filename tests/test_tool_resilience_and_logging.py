"""
Tests for tool resilience, argument tolerance (**kwargs), menu item fuzzy resolution,
and structured logging.
"""

import unittest
import tools
import app


class TestToolResilienceAndLogging(unittest.TestCase):

    def test_place_order_with_extra_kwargs(self):
        """place_order must safely accept extra arguments passed by LLMs (e.g. delivery_time, address)."""
        res = tools.place_order(
            items=[{"menu_id": "M1", "quantity": 1}, {"menu_id": "D1", "quantity": 1}],
            order_type="delivery",
            customer_name="Hasan Rahman",
            customer_phone="07999999999",
            customer_email="test@example.com",
            delivery_time="19:30",
            delivery_address="10 Downing Street, London",
            special_instructions="Ring the bell twice",
            arbitrary_extra_param="some value"
        )
        self.assertTrue(res.get("success"), f"Expected success but got: {res}")
        self.assertEqual(res.get("total"), 17.50)
        self.assertEqual(len(res.get("items")), 2)
        self.assertTrue(res.get("order_id").startswith("O"))

    def test_place_order_with_menu_names_and_case_insensitive_ids(self):
        """place_order must resolve items by exact name, fuzzy substring, or lowercase ID."""
        # 1. Lowercase ID
        res1 = tools.place_order(
            items=[{"menu_id": "m1", "quantity": 1}],
            order_type="pickup",
            customer_name="Alice",
            customer_phone="07123456789",
            customer_email="alice@example.com"
        )
        self.assertTrue(res1.get("success"), f"Failed for lowercase id: {res1}")
        self.assertEqual(res1["items"][0]["menu_id"], "M1")

        # 2. Exact item name
        res2 = tools.place_order(
            items=[{"menu_id": "Chargrilled Chicken Burger", "quantity": 1}],
            order_type="pickup",
            customer_name="Bob",
            customer_phone="07123456789",
            customer_email="bob@example.com"
        )
        self.assertTrue(res2.get("success"), f"Failed for item name: {res2}")
        self.assertEqual(res2["items"][0]["name"], "Chargrilled Chicken Burger")

        # 3. Fuzzy substring in name
        res3 = tools.place_order(
            items=[{"menu_id": "chicken burger", "quantity": 2}, {"name": "fries", "quantity": 1}],
            order_type="delivery",
            customer_name="Charlie",
            customer_phone="07123456789",
            customer_email="charlie@example.com"
        )
        self.assertTrue(res3.get("success"), f"Failed for fuzzy names: {res3}")
        self.assertEqual(res3["items"][0]["menu_id"], "M1")
        self.assertEqual(res3["items"][1]["menu_id"], "D1")

    def test_place_order_validation_failures(self):
        """place_order should return structured error dictionary on invalid inputs without crashing."""
        # Invalid phone
        res_phone = tools.place_order(
            items=[{"menu_id": "M1", "quantity": 1}],
            order_type="delivery",
            customer_name="Dave",
            customer_phone="not-a-number",
            customer_email="dave@example.com"
        )
        self.assertFalse(res_phone["success"])
        self.assertIn("phone", res_phone["reason"].lower())

        # Invalid email
        res_email = tools.place_order(
            items=[{"menu_id": "M1", "quantity": 1}],
            order_type="delivery",
            customer_name="Dave",
            customer_phone="07123456789",
            customer_email="bad-email"
        )
        self.assertFalse(res_email["success"])
        self.assertIn("email", res_email["reason"].lower())

        # Unknown menu item
        res_item = tools.place_order(
            items=[{"menu_id": "X99_NON_EXISTENT", "quantity": 1}],
            order_type="delivery",
            customer_name="Dave",
            customer_phone="07123456789",
            customer_email="dave@example.com"
        )
        self.assertFalse(res_item["success"])
        self.assertIn("unknown menu item", res_item["reason"].lower())

    def test_table_tools_accept_extra_kwargs(self):
        """book_table and check_table_availability must tolerate extra kwargs."""
        avail = tools.check_table_availability(
            date="2026-11-20",
            time="19:00",
            party_size=4,
            customer_name="Test Guest",
            notes="window seat preferred"
        )
        self.assertTrue(avail.get("available"))

        booking = tools.book_table(
            date="2026-11-20",
            time="19:00",
            party_size=4,
            customer_name="Test Guest",
            customer_phone="07123456789",
            special_requests="high chair needed",
            notes="celebrating anniversary"
        )
        self.assertTrue(booking.get("success"))
        self.assertTrue(booking.get("reservation_id").startswith("R"))

    def test_app_run_tool_wrapper(self):
        """app.run_tool must execute tools, log appropriately, and handle unknown tools gracefully."""
        res_unknown = app.run_tool("restaurant", "unknown_tool_name", {"some": "arg"})
        self.assertIn("error", res_unknown)

        res_menu = app.run_tool("restaurant", "get_menu", {"extra": "ignored"})
        self.assertIn("menu", res_menu)


if __name__ == "__main__":
    unittest.main()
