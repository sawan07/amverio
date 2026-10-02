"""
The agent's tool layer: the only things the LLM is allowed to actually DO.
Everything else is just conversation. This is the same pattern as the
Amverio appointment agent -- a small set of functions wrapping the booking
engine -- with a second toolset (menu / order) added for the restaurant.

Each function returns a plain dict, which gets serialised back to the model
as a tool result. Keep these boring and predictable: the model should never
need to guess what happened.
"""

import re
from datetime import datetime, timedelta
from data import (
    BUSINESS, TABLES, MENU, MENU_BY_ID,
    RESERVATIONS, ORDERS, DEFAULT_SEATING_MINUTES,
    next_reservation_id, next_order_id,
)


def _parse_dt(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")


def _is_valid_uk_phone(phone: str) -> bool:
    """
    Validates common UK phone formats (mobile + landline), tolerant of
    spacing/punctuation: "07123 456789", "07123456789", "+44 7123 456789",
    "+447123456789", "0044 7123 456789", "020 1234 5678", "01632 960001".

    Not a full libphonenumber-grade check -- this is a demo guardrail, not
    a telecoms validator. It just rejects obviously-wrong input (too short,
    wrong country, random text) before a booking/order gets created.
    """
    if not phone or not isinstance(phone, str):
        return False

    cleaned = re.sub(r"[\s\-\.\(\)]", "", phone)

    if cleaned.startswith("+44"):
        digits = cleaned[3:]
    elif cleaned.startswith("0044"):
        digits = cleaned[4:]
    elif cleaned.startswith("44") and len(cleaned) >= 12:
        digits = cleaned[2:]
    elif cleaned.startswith("0"):
        digits = cleaned[1:]
    else:
        return False

    if not digits.isdigit():
        return False

    # UK national numbers are 10 digits after the trunk "0" / country code
    # (a handful of legacy landline ranges are 9) -- allow both.
    return len(digits) in (9, 10)


def _table_is_free(table_id: str, start: datetime, end: datetime) -> bool:
    for r in RESERVATIONS:
        if r["table_id"] != table_id or r["status"] != "CONFIRMED":
            continue
        r_start = _parse_dt(r["date"], r["time"])
        r_end = r_start + timedelta(minutes=DEFAULT_SEATING_MINUTES)
        if start < r_end and end > r_start:
            return False
    return True


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def get_menu() -> dict:
    """Return the full menu, grouped by category."""
    by_category = {}
    for item in MENU:
        by_category.setdefault(item["category"], []).append({
            "id": item["id"],
            "name": item["name"],
            "price": item["price"],
            "description": item["description"],
        })
    return {"restaurant": BUSINESS["name"], "currency": BUSINESS["currency"], "menu": by_category}


def check_table_availability(date: str, time: str, party_size: int) -> dict:
    """
    date: 'YYYY-MM-DD', time: 'HH:MM' (24h), party_size: number of guests.
    Returns whether a table is free, and which table would be offered.
    """
    start = _parse_dt(date, time)
    if start < datetime.now():
        return {
            "available": False,
            "date": date,
            "time": time,
            "party_size": party_size,
            "reason": "That date/time has already passed.",
        }
    end = start + timedelta(minutes=DEFAULT_SEATING_MINUTES)

    candidates = [t for t in TABLES if t["seats"] >= party_size]
    candidates.sort(key=lambda t: t["seats"])  # smallest table that fits, first

    for table in candidates:
        if _table_is_free(table["id"], start, end):
            return {
                "available": True,
                "date": date,
                "time": time,
                "party_size": party_size,
                "table_id": table["id"],
            }

    return {
        "available": False,
        "date": date,
        "time": time,
        "party_size": party_size,
        "reason": "No table of sufficient size is free at that time.",
    }


def book_table(date: str, time: str, party_size: int, customer_name: str, customer_phone: str) -> dict:
    """
    Books a table if one is available. Always call check_table_availability
    first in conversation, but this re-checks itself before committing.
    """
    if not _is_valid_uk_phone(customer_phone):
        return {
            "success": False,
            "reason": "That doesn't look like a valid UK phone number. Please provide one, e.g. 07123 456789 or +44 7123 456789.",
        }

    availability = check_table_availability(date, time, party_size)
    if not availability["available"]:
        return {"success": False, "reason": availability.get("reason", "No table available.")}

    reservation = {
        "id": next_reservation_id(),
        "table_id": availability["table_id"],
        "date": date,
        "time": time,
        "party_size": party_size,
        "name": customer_name,
        "phone": customer_phone,
        "status": "CONFIRMED",
    }
    RESERVATIONS.append(reservation)
    return {"success": True, "reservation_id": reservation["id"], **reservation}


def cancel_reservation(reservation_id: str) -> dict:
    for r in RESERVATIONS:
        if r["id"] == reservation_id and r["status"] == "CONFIRMED":
            r["status"] = "CANCELLED"
            return {"success": True, "reservation_id": reservation_id}
    return {"success": False, "reason": "Reservation not found or already cancelled."}


def place_order(items: list, order_type: str, customer_name: str, customer_phone: str) -> dict:
    """
    items: list of {"menu_id": str, "quantity": int}
    order_type: "pickup" or "delivery" -- this is ONLY a label for now.
    No delivery logistics and no payment are handled at this stage; the
    order is simply recorded as taken, to be paid for on collection/delivery.
    """
    if order_type not in ("pickup", "delivery"):
        return {"success": False, "reason": "order_type must be 'pickup' or 'delivery'."}

    if not _is_valid_uk_phone(customer_phone):
        return {
            "success": False,
            "reason": "That doesn't look like a valid UK phone number. Please provide one, e.g. 07123 456789 or +44 7123 456789.",
        }

    line_items = []
    total = 0.0
    for entry in items:
        menu_item = MENU_BY_ID.get(entry["menu_id"])
        if not menu_item:
            return {"success": False, "reason": f"Unknown menu item: {entry['menu_id']}"}
        qty = entry.get("quantity", 1)
        line_total = menu_item["price"] * qty
        total += line_total
        line_items.append({
            "menu_id": menu_item["id"],
            "name": menu_item["name"],
            "quantity": qty,
            "unit_price": menu_item["price"],
            "line_total": round(line_total, 2),
        })

    order = {
        "id": next_order_id(),
        "items": line_items,
        "order_type": order_type,
        "name": customer_name,
        "phone": customer_phone,
        "status": "RECEIVED",
        "total": round(total, 2),
        "payment": "pay on collection" if order_type == "pickup" else "pay on delivery",
    }
    ORDERS.append(order)
    return {"success": True, "order_id": order["id"], **order}


# ---------------------------------------------------------------------------
# Tool schemas -- Claude Messages API "tools" format. If the provider turns
# out to be OpenAI instead, these translate almost 1:1 into its function
# schema (same fields, different envelope).
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "get_menu",
        "description": "Get the full restaurant menu, grouped by category, with prices.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_table_availability",
        "description": "Check whether a table is free for a given date, time, and party size.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "HH:MM, 24-hour"},
                "party_size": {"type": "integer"},
            },
            "required": ["date", "time", "party_size"],
        },
    },
    {
        "name": "book_table",
        "description": "Book a table. Only call after confirming availability and getting the customer's name and phone number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "time": {"type": "string"},
                "party_size": {"type": "integer"},
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string"},
            },
            "required": ["date", "time", "party_size", "customer_name", "customer_phone"],
        },
    },
    {
        "name": "cancel_reservation",
        "description": "Cancel an existing table reservation by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {"reservation_id": {"type": "string"}},
            "required": ["reservation_id"],
        },
    },
    {
        "name": "place_order",
        "description": (
            "Place a food order for pickup or delivery. No payment is taken through this tool -- "
            "the order is recorded and the customer pays on collection or on delivery. "
            "Only call this once the customer has confirmed their full order and order type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "menu_id": {"type": "string"},
                            "quantity": {"type": "integer"},
                        },
                        "required": ["menu_id", "quantity"],
                    },
                },
                "order_type": {"type": "string", "enum": ["pickup", "delivery"]},
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string"},
            },
            "required": ["items", "order_type", "customer_name", "customer_phone"],
        },
    },
]

TOOL_FUNCTIONS = {
    "get_menu": lambda **kwargs: get_menu(),
    "check_table_availability": lambda **kwargs: check_table_availability(**kwargs),
    "book_table": lambda **kwargs: book_table(**kwargs),
    "cancel_reservation": lambda **kwargs: cancel_reservation(**kwargs),
    "place_order": lambda **kwargs: place_order(**kwargs),
}
