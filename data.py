"""
In-memory demo data for the Amverio restaurant agent prototype.

This is intentionally NOT the real Booking.System backend. Per the agreed
build order (agent logic first, WhatsApp/backend wiring after), this lets us
prove the conversation + tool-calling flow works before we touch the real
Kotlin backend, WhatsApp Business Platform, or your production database.

Once the logic is proven out, the same tool functions in tools.py get
re-pointed at real HTTP calls into booking-system-backend instead of these
in-memory lists (table booking would reuse the existing AvailabilityEngine;
menu/order handling is genuinely new).
"""

from datetime import datetime, time
import itertools

# ---------------------------------------------------------------------------
# Business identity (invented demo persona, same role "Luxe Locks" plays for
# the salon demo -- feel free to rename/reflavour before this goes live)
# ---------------------------------------------------------------------------

BUSINESS = {
    "name": "The Copper Fork",
    "cuisine": "Modern British bistro & grill",
    "currency": "GBP",
    "address": "14 Mill Lane, demo location",
    "opening_hours": {
        # Tue-Sun 12:00-22:00, closed Monday
        "mon": None,
        "tue": (time(12, 0), time(22, 0)),
        "wed": (time(12, 0), time(22, 0)),
        "thu": (time(12, 0), time(22, 0)),
        "fri": (time(12, 0), time(22, 30)),
        "sat": (time(12, 0), time(22, 30)),
        "sun": (time(12, 0), time(21, 0)),
    },
}

# ---------------------------------------------------------------------------
# Tables -- bookable resource for table booking (distinct from menu items).
# Each table has a fixed seat count; booking picks any table that fits the
# party size and is free at that time, same "any available resource" pattern
# as staff fallback in the existing AvailabilityEngine.
# ---------------------------------------------------------------------------

TABLES = [
    {"id": "T1", "seats": 2},
    {"id": "T2", "seats": 2},
    {"id": "T3", "seats": 4},
    {"id": "T4", "seats": 4},
    {"id": "T5", "seats": 4},
    {"id": "T6", "seats": 6},
    {"id": "T7", "seats": 6},
    {"id": "T8", "seats": 8},
]

DEFAULT_SEATING_MINUTES = 90  # how long a table is considered occupied per booking

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

MENU = [
    {"id": "S1", "category": "Starters", "name": "Soup of the Day", "price": 6.50,
     "description": "Ask for today's flavour, served with sourdough."},
    {"id": "S2", "category": "Starters", "name": "Garlic Flatbread", "price": 5.50,
     "description": "Stone-baked flatbread, garlic butter, herbs."},

    {"id": "M1", "category": "Mains", "name": "Chargrilled Chicken Burger", "price": 13.50,
     "description": "Buttermilk chicken, smoked bacon, fries."},
    {"id": "M2", "category": "Mains", "name": "8oz Sirloin Steak", "price": 19.00,
     "description": "Chargrilled sirloin, peppercorn sauce, fries."},
    {"id": "M3", "category": "Mains", "name": "Wild Mushroom Risotto", "price": 12.50,
     "description": "Vegetarian. Arborio rice, wild mushrooms, parmesan."},
    {"id": "M4", "category": "Mains", "name": "Beer-Battered Fish & Chips", "price": 14.00,
     "description": "Market fish, mushy peas, tartare sauce."},

    {"id": "D1", "category": "Sides", "name": "Skin-On Fries", "price": 4.00, "description": ""},
    {"id": "D2", "category": "Sides", "name": "Seasonal Greens", "price": 4.00, "description": ""},

    {"id": "P1", "category": "Desserts", "name": "Sticky Toffee Pudding", "price": 6.00,
     "description": "Butterscotch sauce, vanilla ice cream."},
    {"id": "P2", "category": "Desserts", "name": "Chocolate Brownie", "price": 6.00,
     "description": "Warm brownie, vanilla ice cream."},
]

MENU_BY_ID = {item["id"]: item for item in MENU}

# ---------------------------------------------------------------------------
# In-memory state -- reset any time by restarting the process. Swapped for
# real persistence (and real endpoints) once this graduates out of prototype.
# ---------------------------------------------------------------------------

from datetime import datetime, time, timedelta
import itertools

_reservation_ids = itertools.count(4)
_order_ids = itertools.count(4)

RESERVATIONS = [
    {
        "id": "R0001",
        "table_id": "T4",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": "19:00",
        "party_size": 4,
        "name": "Sarah Jenkins",
        "phone": "+44 7700 900123",
        "status": "CONFIRMED",
        "created_at": "Today 14:15",
    },
    {
        "id": "R0002",
        "table_id": "T1",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": "20:30",
        "party_size": 2,
        "name": "David Miller",
        "phone": "+44 7700 900456",
        "status": "CONFIRMED",
        "created_at": "Today 15:40",
    },
    {
        "id": "R0003",
        "table_id": "T6",
        "date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        "time": "18:30",
        "party_size": 6,
        "name": "Emma Watson",
        "phone": "+44 7700 900789",
        "status": "CONFIRMED",
        "created_at": "Today 16:20",
    },
]

ORDERS = [
    {
        "id": "O0001",
        "items": [
            {"menu_id": "M2", "name": "8oz Sirloin Steak", "quantity": 2, "unit_price": 19.00, "line_total": 38.00},
            {"menu_id": "D1", "name": "Skin-On Fries", "quantity": 2, "unit_price": 4.00, "line_total": 8.00},
            {"menu_id": "P1", "name": "Sticky Toffee Pudding", "quantity": 2, "unit_price": 6.00, "line_total": 12.00},
        ],
        "order_type": "delivery",
        "name": "James Henderson",
        "phone": "+44 7700 900321",
        "email": "james.h@example.co.uk",
        "status": "PAID",
        "total": 58.00,
        "payment": "Stripe Sandbox",
        "payment_link": "https://checkout.stripe.com/demo/o0001",
        "email_sent_to": "james.h@example.co.uk",
        "email_status": "sent",
        "created_at": "Today 18:25",
    },
    {
        "id": "O0002",
        "items": [
            {"menu_id": "M1", "name": "Chargrilled Chicken Burger", "quantity": 1, "unit_price": 13.50, "line_total": 13.50},
            {"menu_id": "M4", "name": "Beer-Battered Fish & Chips", "quantity": 1, "unit_price": 14.00, "line_total": 14.00},
            {"menu_id": "S2", "name": "Garlic Flatbread", "quantity": 1, "unit_price": 5.50, "line_total": 5.50},
        ],
        "order_type": "collection",
        "name": "Oliver Twist",
        "phone": "+44 7700 900654",
        "email": "oliver@example.co.uk",
        "status": "PREPARING",
        "total": 33.00,
        "payment": "Stripe Sandbox",
        "payment_link": "https://checkout.stripe.com/demo/o0002",
        "email_sent_to": "oliver@example.co.uk",
        "email_status": "sent",
        "created_at": "Today 19:10",
    },
    {
        "id": "O0003",
        "items": [
            {"menu_id": "M3", "name": "Wild Mushroom Risotto", "quantity": 1, "unit_price": 12.50, "line_total": 12.50},
            {"menu_id": "S1", "name": "Soup of the Day", "quantity": 1, "unit_price": 6.50, "line_total": 6.50},
            {"menu_id": "P2", "name": "Chocolate Brownie", "quantity": 1, "unit_price": 6.00, "line_total": 6.00},
        ],
        "order_type": "collection",
        "name": "Charlotte Bronte",
        "phone": "+44 7700 900987",
        "email": "charlotte@example.co.uk",
        "status": "RECEIVED",
        "total": 25.00,
        "payment": "Stripe Sandbox",
        "payment_link": "https://checkout.stripe.com/demo/o0003",
        "email_sent_to": "charlotte@example.co.uk",
        "email_status": "sent",
        "created_at": "Today 19:45",
    },
]


def next_reservation_id():
    return f"R{next(_reservation_ids):04d}"


def next_order_id():
    return f"O{next(_order_ids):04d}"
