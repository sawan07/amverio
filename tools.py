"""
The agent's tool layer: the only things the LLM is allowed to actually DO.
Everything else is just conversation. This is the same pattern as the
Amverio appointment agent -- a small set of functions wrapping the booking
engine -- with a second toolset (menu / order) added for the restaurant.

Each function returns a plain dict, which gets serialised back to the model
as a tool result. Keep these boring and predictable: the model should never
need to guess what happened.
"""

import os
import re
import json
import smtplib
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime, timedelta
from data import (
    BUSINESS, TABLES, MENU, MENU_BY_ID,
    DEFAULT_SEATING_MINUTES,
    next_reservation_id, next_order_id,
)
import db

# Load .env file if present
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    try:
        with open(_env_file) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
    except Exception:
        pass


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
    for r in db.get_reservations():
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
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    db.add_reservation(reservation)
    return {"success": True, "reservation_id": reservation["id"], **reservation}


def cancel_reservation(reservation_id: str) -> dict:
    updated = db.update_reservation_status(reservation_id, "CANCELLED")
    if updated:
        return {"success": True, "reservation_id": reservation_id}
    return {"success": False, "reason": "Reservation not found or already cancelled."}


def _is_valid_email(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def _create_stripe_payment_link(order_id: str, line_items: list, total: float, customer_email: str, customer_name: str) -> str:
    """
    Creates a Stripe Payment Link (https://buy.stripe.com/test_...) in sandbox/test mode.
    Payment Links are clean, direct URLs without fragile client-side #hash fragments that
    get truncated by LLMs or messaging apps.
    Falls back to Checkout Sessions or demo link if necessary.
    """
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not stripe_key:
        return f"https://checkout.stripe.com/c/pay/cs_test_demo_{order_id.lower()}#order={order_id}"

    # 1. Primary: Stripe Payment Links API (clean, robust https://buy.stripe.com/test_... URLs)
    try:
        pl_fields = [
            ("metadata[order_id]", order_id),
            ("metadata[customer_name]", customer_name),
            ("metadata[customer_email]", customer_email),
            ("restrictions[completed_sessions][limit]", "1"),
        ]
        for idx, item in enumerate(line_items):
            unit_pence = int(round(item["unit_price"] * 100))
            price_data = urllib.parse.urlencode({
                "currency": "gbp",
                "unit_amount": str(unit_pence),
                "product_data[name]": item["name"],
            }).encode("utf-8")
            price_req = urllib.request.Request(
                "https://api.stripe.com/v1/prices",
                data=price_data,
                headers={"Authorization": f"Bearer {stripe_key}"},
                method="POST",
            )
            with urllib.request.urlopen(price_req, timeout=10) as p_resp:
                price = json.loads(p_resp.read().decode("utf-8"))
                pl_fields.append((f"line_items[{idx}][price]", price["id"]))
                pl_fields.append((f"line_items[{idx}][quantity]", str(item["quantity"])))

        pl_req = urllib.request.Request(
            "https://api.stripe.com/v1/payment_links",
            data=urllib.parse.urlencode(pl_fields).encode("utf-8"),
            headers={"Authorization": f"Bearer {stripe_key}"},
            method="POST",
        )
        with urllib.request.urlopen(pl_req, timeout=10) as pl_resp:
            pl_json = json.loads(pl_resp.read().decode("utf-8"))
            if pl_json.get("url"):
                return pl_json["url"]
    except Exception as e:
        print(f"Stripe Payment Links API error: {e}, falling back to Checkout Sessions")

    # 2. Secondary fallback: Checkout Sessions
    try:
        form_fields = [
            ("mode", "payment"),
            ("customer_email", customer_email),
            ("success_url", "https://amverio.co.uk/order-success?session_id={CHECKOUT_SESSION_ID}"),
            ("cancel_url", "https://amverio.co.uk/order-cancel"),
            ("client_reference_id", order_id),
            ("metadata[order_id]", order_id),
            ("metadata[customer_name]", customer_name),
        ]
        for idx, item in enumerate(line_items):
            unit_pence = int(round(item["unit_price"] * 100))
            form_fields.append((f"line_items[{idx}][price_data][currency]", "gbp"))
            form_fields.append((f"line_items[{idx}][price_data][unit_amount]", str(unit_pence)))
            form_fields.append((f"line_items[{idx}][price_data][product_data][name]", item["name"]))
            form_fields.append((f"line_items[{idx}][quantity]", str(item["quantity"])))

        encoded_data = urllib.parse.urlencode(form_fields).encode("utf-8")
        req = urllib.request.Request(
            "https://api.stripe.com/v1/checkout/sessions",
            data=encoded_data,
            headers={
                "Authorization": f"Bearer {stripe_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("url") or f"https://checkout.stripe.com/c/pay/{data.get('id')}"
    except Exception as e:
        print(f"Stripe session error: {e}")
        return f"https://checkout.stripe.com/c/pay/cs_test_demo_{order_id.lower()}#order={order_id}"


def _send_brevo_confirmation_email(
    order_id: str,
    customer_name: str,
    customer_email: str,
    order_type: str,
    line_items: list,
    total: float,
    payment_link: str,
) -> dict:
    """
    Sends an order confirmation email via Brevo SMTP relay or REST API.
    Falls back gracefully if credentials are missing or send fails.
    """
    smtp_host = os.environ.get("SMTP_HOST", "smtp-relay.brevo.com").strip()
    smtp_port_val = os.environ.get("SMTP_PORT", "587").strip()
    smtp_port = int(smtp_port_val) if smtp_port_val.isdigit() else 587
    smtp_user = os.environ.get("SMTP_USER", "").strip() or os.environ.get("BREVO_SENDER_EMAIL", "").strip()
    smtp_pass = os.environ.get("SMTP_PASSWORD", "").strip() or os.environ.get("BREVO_API_KEY", "").strip()

    sender_email = os.environ.get("BREVO_SENDER_EMAIL", "").strip() or smtp_user or "orders@amverio.co.uk"
    sender_name = os.environ.get("BREVO_SENDER_NAME", "").strip() or "The Copper Fork"

    items_rows = "".join(
        f"<tr>"
        f"<td style='padding:8px 0; border-bottom:1px solid #eee;'>{item['quantity']}x {item['name']}</td>"
        f"<td style='padding:8px 0; border-bottom:1px solid #eee; text-align:right;'>£{item['line_total']:.2f}</td>"
        f"</tr>"
        for item in line_items
    )

    html_content = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #222;">
        <h2 style="color: #0b1a2d; margin-top: 0;">Order Confirmation - #{order_id}</h2>
        <p>Hi {customer_name},</p>
        <p>Thank you for ordering with <strong>The Copper Fork</strong>! Here is your order breakdown:</p>
        
        <div style="background: #f8f9fa; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <p style="margin: 0 0 10px 0;"><strong>Order Type:</strong> {order_type.capitalize()}</p>
            <table style="width: 100%; border-collapse: collapse;">
                <tbody>
                    {items_rows}
                    <tr>
                        <td style="padding: 12px 0 0 0; font-weight: bold; font-size: 16px;">Total</td>
                        <td style="padding: 12px 0 0 0; font-weight: bold; font-size: 16px; text-align: right;">£{total:.2f}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div style="text-align: center; margin: 28px 0;">
            <a href="{payment_link}" style="background: #0070f3; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: bold; display: inline-block;">Pay Now via Stripe (£{total:.2f})</a>
        </div>
        <p style="font-size: 13px; color: #666; text-align: center;">Or copy this payment link:<br><a href="{payment_link}" style="color: #0070f3;">{payment_link}</a></p>
        
        <p style="color: #888; font-size: 12px; margin-top: 30px; border-top: 1px solid #eee; padding-top: 16px;">
            The Copper Fork · 12 King Street, London · 020 7946 0123
        </p>
    </div>
    """

    text_content = (
        f"Order Confirmation - #{order_id}\n\n"
        f"Hi {customer_name},\n\n"
        f"Thank you for ordering with The Copper Fork!\n"
        f"Order Type: {order_type.capitalize()}\n\n"
        f"Items:\n" + "\n".join(f"- {i['quantity']}x {i['name']}: £{i['line_total']:.2f}" for i in line_items) + "\n\n"
        f"Total: £{total:.2f}\n\n"
        f"Pay securely with Stripe:\n{payment_link}\n\n"
        f"The Copper Fork · 12 King Street, London\n"
    )

    # 1. Try sending via SMTP if SMTP credentials are provided
    if smtp_user and smtp_pass:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Order Confirmation #{order_id} - The Copper Fork"
            msg["From"] = formataddr((sender_name, sender_email))
            msg["To"] = formataddr((customer_name, customer_email))
            msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
                server.ehlo()
                server.starttls()
                server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender_email, [customer_email], msg.as_string())
            server.quit()
            print(f"Brevo email sent successfully via SMTP to {customer_email}")
            return {"sent": True, "method": "smtp", "recipient": customer_email}
        except Exception as e:
            print(f"Brevo SMTP send error: {e}")

    # 2. Try sending via REST API if key starts with xkeysib
    brevo_api_key = os.environ.get("BREVO_API_KEY", "").strip()
    if brevo_api_key and brevo_api_key.startswith("xkeysib"):
        try:
            payload = {
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": customer_email, "name": customer_name}],
                "subject": f"Order Confirmation #{order_id} - The Copper Fork",
                "htmlContent": html_content,
                "textContent": text_content,
            }
            req = urllib.request.Request(
                "https://api.brevo.com/v3/smtp/email",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "api-key": brevo_api_key,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"Brevo email sent successfully via REST API to {customer_email}")
                return {"sent": True, "method": "api", "recipient": customer_email}
        except Exception as e:
            print(f"Brevo REST API error: {e}")

    # Simulated fallback if no send succeeded
    return {"sent": False, "simulated": True, "recipient": customer_email}


def place_order(
    items: list,
    order_type: str,
    customer_name: str,
    customer_phone: str,
    customer_email: str = "",
) -> dict:
    """
    items: list of {"menu_id": str, "quantity": int}
    order_type: "pickup" or "delivery"
    customer_name: customer's full name
    customer_phone: valid UK phone number
    customer_email: customer's email address for confirmation receipt & payment link
    """
    if order_type not in ("pickup", "delivery"):
        return {"success": False, "reason": "order_type must be 'pickup' or 'delivery'."}

    if not _is_valid_uk_phone(customer_phone):
        return {
            "success": False,
            "reason": "That doesn't look like a valid UK phone number. Please provide one, e.g. 07123 456789 or +44 7123 456789.",
        }

    if not _is_valid_email(customer_email):
        return {
            "success": False,
            "reason": "Please provide a valid email address (e.g. name@example.com) so we can send your order confirmation.",
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

    order_id = next_order_id()
    round_total = round(total, 2)
    payment_link = _create_stripe_payment_link(order_id, line_items, round_total, customer_email, customer_name)
    email_result = _send_brevo_confirmation_email(
        order_id=order_id,
        customer_name=customer_name,
        customer_email=customer_email,
        order_type=order_type,
        line_items=line_items,
        total=round_total,
        payment_link=payment_link,
    )

    order = {
        "id": order_id,
        "items": line_items,
        "order_type": order_type,
        "name": customer_name,
        "phone": customer_phone,
        "email": customer_email,
        "status": "RECEIVED",
        "total": round_total,
        "payment": "Stripe Sandbox",
        "payment_link": payment_link,
        "email_sent_to": customer_email,
        "email_status": "sent" if email_result.get("sent") else ("simulated" if email_result.get("simulated") else "failed"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    db.add_order(order)
    return {
        "success": True,
        "order_id": order["id"],
        "total": order["total"],
        "payment_link": payment_link,
        "email_sent_to": customer_email,
        "order_type": order_type,
        "items": line_items,
        "customer_name": customer_name,
    }


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
            "Place a food order for pickup or delivery, send an email confirmation with order details via Brevo, "
            "and generate a Stripe sandbox payment link. "
            "Only call this once the customer has confirmed their full order, order type, "
            "name, UK phone number, and email address."
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
                "customer_email": {"type": "string", "description": "Customer email address for confirmation receipt and payment link"},
            },
            "required": ["items", "order_type", "customer_name", "customer_phone", "customer_email"],
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
