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

_reservation_ids = itertools.count(1)
_order_ids = itertools.count(1)

RESERVATIONS = []  # {id, table_id, date, time, party_size, name, phone, status}
ORDERS = []         # {id, items, order_type, name, phone, status, total}


def next_reservation_id():
    return f"R{next(_reservation_ids):04d}"


def next_order_id():
    return f"O{next(_order_ids):04d}"
