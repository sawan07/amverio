"""
Database persistence layer for Amverio.

Supports:
1. PostgreSQL (production on Coolify when DATABASE_URL is set).
2. SQLite (local dev and fallback when DATABASE_URL is unset).

Automatically initializes schemas and seeds initial demo records if empty.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, Any

log = logging.getLogger("amverio.db")

_here = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB_PATH = os.path.join(_here, "amverio.db")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Check if psycopg2 is available
try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False


def _is_postgres() -> bool:
    return bool(DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")) and _HAS_PSYCOPG2)


def _get_connection():
    if _is_postgres():
        try:
            # psycopg2 handles both postgres:// and postgresql://
            url = DATABASE_URL
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://"):]
            conn = psycopg2.connect(url, connect_timeout=5)
            conn.autocommit = True
            return conn
        except Exception as e:
            log.warning("PostgreSQL connection failed (%s); falling back to SQLite (%s)", e, SQLITE_DB_PATH)
    
    # SQLite fallback
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database tables and seed default records if empty."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()

    try:
        # Schema
        if is_pg:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id VARCHAR(64) PRIMARY KEY,
                items TEXT NOT NULL,
                order_type VARCHAR(64),
                name VARCHAR(255),
                phone VARCHAR(64),
                email VARCHAR(255),
                status VARCHAR(64),
                total NUMERIC(10, 2),
                payment VARCHAR(128),
                payment_link TEXT,
                email_sent_to VARCHAR(255),
                email_status VARCHAR(64),
                created_at VARCHAR(64)
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS reservations (
                id VARCHAR(64) PRIMARY KEY,
                table_id VARCHAR(32) NOT NULL,
                date VARCHAR(32) NOT NULL,
                time VARCHAR(32) NOT NULL,
                party_size INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                phone VARCHAR(64) NOT NULL,
                status VARCHAR(64) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                reminder_sent_at VARCHAR(64)
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_sessions (
                phone_number VARCHAR(64) PRIMARY KEY,
                last_inbound_at DOUBLE PRECISION NOT NULL,
                last_message_text TEXT,
                last_outbound_at DOUBLE PRECISION,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            );
            """)
        else:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                items TEXT NOT NULL,
                order_type TEXT,
                name TEXT,
                phone TEXT,
                email TEXT,
                status TEXT,
                total REAL,
                payment TEXT,
                payment_link TEXT,
                email_sent_to TEXT,
                email_status TEXT,
                created_at TEXT
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS reservations (
                id TEXT PRIMARY KEY,
                table_id TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                party_size INTEGER NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reminder_sent_at TEXT
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_sessions (
                phone_number TEXT PRIMARY KEY,
                last_inbound_at REAL NOT NULL,
                last_message_text TEXT,
                last_outbound_at REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)
            conn.commit()

        # Schema migrations for existing tables
        try:
            if is_pg:
                cur.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS reminder_sent_at VARCHAR(64);")
            else:
                cur.execute("PRAGMA table_info(reservations);")
                columns = [row[1] for row in cur.fetchall()]
                if "reminder_sent_at" not in columns:
                    cur.execute("ALTER TABLE reservations ADD COLUMN reminder_sent_at TEXT;")
                    conn.commit()
        except Exception as e:
            log.warning("Could not add reminder_sent_at column to reservations: %s", e)

        # Check if orders need seeding
        cur.execute("SELECT COUNT(*) FROM orders;")
        order_count = cur.fetchone()[0]
        if order_count == 0:
            _seed_orders(cur, is_pg)
            if not is_pg:
                conn.commit()

        # Check if reservations need seeding
        cur.execute("SELECT COUNT(*) FROM reservations;")
        res_count = cur.fetchone()[0]
        if res_count == 0:
            _seed_reservations(cur, is_pg)
            if not is_pg:
                conn.commit()

        log.info("Database initialized successfully (engine=%s)", "PostgreSQL" if is_pg else "SQLite")
    finally:
        cur.close()
        conn.close()


def _seed_orders(cur, is_pg: bool) -> None:
    initial_orders = [
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
            "payment_link": "https://buy.stripe.com/test_00wdRbgJlcq",
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
            "payment_link": "https://buy.stripe.com/test_00wdRbgJlcq",
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
            "payment_link": "https://buy.stripe.com/test_00wdRbgJlcq",
            "email_sent_to": "charlotte@example.co.uk",
            "email_status": "sent",
            "created_at": "Today 19:45",
        },
    ]

    sql = """
    INSERT INTO orders (id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """ if is_pg else """
    INSERT INTO orders (id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    for o in initial_orders:
        cur.execute(sql, (
            o["id"],
            json.dumps(o["items"]),
            o["order_type"],
            o["name"],
            o["phone"],
            o["email"],
            o["status"],
            o["total"],
            o["payment"],
            o["payment_link"],
            o["email_sent_to"],
            o["email_status"],
            o["created_at"],
        ))


def _seed_reservations(cur, is_pg: bool) -> None:
    today_str = datetime.now().strftime("%Y-%m-%d")
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    initial_res = [
        {
            "id": "R0001",
            "table_id": "T4",
            "date": today_str,
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
            "date": today_str,
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
            "date": tomorrow_str,
            "time": "18:30",
            "party_size": 6,
            "name": "Emma Watson",
            "phone": "+44 7700 900789",
            "status": "CONFIRMED",
            "created_at": "Today 16:20",
        },
    ]

    sql = """
    INSERT INTO reservations (id, table_id, date, time, party_size, name, phone, status, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """ if is_pg else """
    INSERT INTO reservations (id, table_id, date, time, party_size, name, phone, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    for r in initial_res:
        cur.execute(sql, (
            r["id"],
            r["table_id"],
            r["date"],
            r["time"],
            r["party_size"],
            r["name"],
            r["phone"],
            r["status"],
            r["created_at"],
        ))


def _row_to_order(row: Any) -> dict:
    if isinstance(row, dict):
        d = dict(row)
    else:
        # SQLite Row or tuple
        try:
            d = dict(row)
        except Exception:
            cols = ["id", "items", "order_type", "name", "phone", "email", "status", "total", "payment", "payment_link", "email_sent_to", "email_status", "created_at"]
            d = dict(zip(cols, row))
    
    # Parse items JSON
    if isinstance(d.get("items"), str):
        try:
            d["items"] = json.loads(d["items"])
        except Exception:
            d["items"] = []
    if d.get("total") is not None:
        d["total"] = float(d["total"])
    return d


def _row_to_reservation(row: Any) -> dict:
    if isinstance(row, dict):
        d = dict(row)
    else:
        try:
            d = dict(row)
        except Exception:
            cols = ["id", "table_id", "date", "time", "party_size", "name", "phone", "status", "created_at", "reminder_sent_at"]
            d = dict(zip(cols, row))
    if d.get("party_size") is not None:
        d["party_size"] = int(d["party_size"])
    return d


def get_orders() -> list[dict]:
    """Retrieve all orders from DB."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at FROM orders ORDER BY id DESC;")
        rows = cur.fetchall()
        return [_row_to_order(r) for r in rows]
    finally:
        cur.close()
        conn.close()


def get_order(order_id: str) -> Optional[dict]:
    """Retrieve a single order by ID."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        sql = "SELECT id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at FROM orders WHERE id = %s;" if is_pg else "SELECT id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at FROM orders WHERE id = ?;"
        cur.execute(sql, (order_id,))
        row = cur.fetchone()
        return _row_to_order(row) if row else None
    finally:
        cur.close()
        conn.close()


def add_order(order: dict) -> dict:
    """Insert a new order into DB."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        sql = """
        INSERT INTO orders (id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """ if is_pg else """
        INSERT INTO orders (id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        items_json = json.dumps(order.get("items", []))
        cur.execute(sql, (
            order["id"],
            items_json,
            order.get("order_type", "collection"),
            order.get("name", "Guest"),
            order.get("phone", ""),
            order.get("email", ""),
            order.get("status", "PENDING_PAYMENT"),
            float(order.get("total", 0.0)),
            order.get("payment", "Standard"),
            order.get("payment_link", ""),
            order.get("email_sent_to", ""),
            order.get("email_status", ""),
            order.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ))
        if not is_pg:
            conn.commit()
        return order
    except Exception as e:
        log.exception("Database error in add_order for %s: %s", order.get("id"), e)
        raise
    finally:
        cur.close()
        conn.close()


def update_order_status(order_id: str, status: str) -> Optional[dict]:
    """Update order status in DB."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        sql = "UPDATE orders SET status = %s WHERE id = %s;" if is_pg else "UPDATE orders SET status = ? WHERE id = ?;"
        cur.execute(sql, (status.strip().upper(), order_id))
        if not is_pg:
            conn.commit()
        
        # Fetch updated
        sel_sql = "SELECT id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at FROM orders WHERE id = %s;" if is_pg else "SELECT id, items, order_type, name, phone, email, status, total, payment, payment_link, email_sent_to, email_status, created_at FROM orders WHERE id = ?;"
        cur.execute(sel_sql, (order_id,))
        row = cur.fetchone()
        return _row_to_order(row) if row else None
    finally:
        cur.close()
        conn.close()


def get_reservations() -> list[dict]:
    """Retrieve all table reservations from DB."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, table_id, date, time, party_size, name, phone, status, created_at, reminder_sent_at FROM reservations ORDER BY id DESC;")
        rows = cur.fetchall()
        return [_row_to_reservation(r) for r in rows]
    finally:
        cur.close()
        conn.close()


def get_reservation(res_id: str) -> Optional[dict]:
    """Retrieve a single reservation by ID."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        sql = "SELECT id, table_id, date, time, party_size, name, phone, status, created_at, reminder_sent_at FROM reservations WHERE id = %s;" if is_pg else "SELECT id, table_id, date, time, party_size, name, phone, status, created_at, reminder_sent_at FROM reservations WHERE id = ?;"
        cur.execute(sql, (res_id,))
        row = cur.fetchone()
        return _row_to_reservation(row) if row else None
    finally:
        cur.close()
        conn.close()


def add_reservation(res: dict) -> dict:
    """Insert a new reservation into DB."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        sql = """
        INSERT INTO reservations (id, table_id, date, time, party_size, name, phone, status, created_at, reminder_sent_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """ if is_pg else """
        INSERT INTO reservations (id, table_id, date, time, party_size, name, phone, status, created_at, reminder_sent_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cur.execute(sql, (
            res["id"],
            res["table_id"],
            res["date"],
            res["time"],
            int(res["party_size"]),
            res["name"],
            res["phone"],
            res["status"],
            res.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
            res.get("reminder_sent_at"),
        ))
        if not is_pg:
            conn.commit()
        return res
    except Exception as e:
        log.exception("Database error in add_reservation for %s: %s", res.get("id"), e)
        raise
    finally:
        cur.close()
        conn.close()


def update_reservation_status(res_id: str, status: str) -> Optional[dict]:
    """Update reservation status in DB."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        sql = "UPDATE reservations SET status = %s WHERE id = %s;" if is_pg else "UPDATE reservations SET status = ? WHERE id = ?;"
        cur.execute(sql, (status.strip().upper(), res_id))
        if not is_pg:
            conn.commit()
        
        sel_sql = "SELECT id, table_id, date, time, party_size, name, phone, status, created_at, reminder_sent_at FROM reservations WHERE id = %s;" if is_pg else "SELECT id, table_id, date, time, party_size, name, phone, status, created_at, reminder_sent_at FROM reservations WHERE id = ?;"
        cur.execute(sel_sql, (res_id,))
        row = cur.fetchone()
        return _row_to_reservation(row) if row else None
    finally:
        cur.close()
        conn.close()


def mark_reservation_reminder_sent(res_id: str, sent_at: Optional[str] = None) -> Optional[dict]:
    """Marks that a booking reminder has been sent for this reservation."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    timestamp = sent_at or datetime.now().isoformat()
    try:
        sql = "UPDATE reservations SET reminder_sent_at = %s WHERE id = %s;" if is_pg else "UPDATE reservations SET reminder_sent_at = ? WHERE id = ?;"
        cur.execute(sql, (timestamp, res_id))
        if not is_pg:
            conn.commit()
        return get_reservation(res_id)
    finally:
        cur.close()
        conn.close()


def get_due_reminders(hours_ahead: float = 3.0, reference_dt: Optional[datetime] = None) -> list[dict]:
    """
    Finds CONFIRMED reservations that have not received a reminder yet (reminder_sent_at IS NULL),
    and whose scheduled date/time is within `hours_ahead` hours from reference_dt (defaulting to now).
    """
    now = reference_dt or datetime.now()
    window_end = now + timedelta(hours=hours_ahead)
    
    all_res = get_reservations()
    due = []
    for r in all_res:
        if r.get("status") != "CONFIRMED":
            continue
        if r.get("reminder_sent_at"):
            continue
        
        date_str = r.get("date", "").strip()
        time_str = r.get("time", "").strip()
        if not date_str or not time_str:
            continue
        
        try:
            res_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        
        if now <= res_dt <= window_end:
            due.append(r)
    return due


# ---------------------------------------------------------------------------
# WhatsApp Session & 24-Hour Window Persistence Layer
# ---------------------------------------------------------------------------

def _row_to_session(row: Any) -> dict:
    if isinstance(row, dict):
        d = dict(row)
    else:
        try:
            d = dict(row)
        except Exception:
            cols = ["phone_number", "last_inbound_at", "last_message_text", "last_outbound_at", "created_at", "updated_at"]
            d = dict(zip(cols, row))
    if d.get("last_inbound_at") is not None:
        d["last_inbound_at"] = float(d["last_inbound_at"])
    if d.get("last_outbound_at") is not None:
        d["last_outbound_at"] = float(d["last_outbound_at"])
    return d


def record_whatsapp_inbound(phone_number: str, message_text: str = "", timestamp: Optional[float] = None) -> dict:
    """
    Records or updates an inbound WhatsApp message timestamp for a phone number.
    Ensures 24-hour customer window is tracked accurately.
    """
    import time
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    now_ts = timestamp if timestamp is not None else time.time()
    now_iso = datetime.now().isoformat()
    phone = phone_number.strip()
    
    try:
        cur.execute("SELECT phone_number FROM whatsapp_sessions WHERE phone_number = %s;" if is_pg else "SELECT phone_number FROM whatsapp_sessions WHERE phone_number = ?;", (phone,))
        existing = cur.fetchone()
        if existing:
            sql = """
            UPDATE whatsapp_sessions
            SET last_inbound_at = %s, last_message_text = %s, updated_at = %s
            WHERE phone_number = %s;
            """ if is_pg else """
            UPDATE whatsapp_sessions
            SET last_inbound_at = ?, last_message_text = ?, updated_at = ?
            WHERE phone_number = ?;
            """
            cur.execute(sql, (now_ts, message_text, now_iso, phone))
        else:
            sql = """
            INSERT INTO whatsapp_sessions (phone_number, last_inbound_at, last_message_text, last_outbound_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s);
            """ if is_pg else """
            INSERT INTO whatsapp_sessions (phone_number, last_inbound_at, last_message_text, last_outbound_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """
            cur.execute(sql, (phone, now_ts, message_text, None, now_iso, now_iso))
        if not is_pg:
            conn.commit()

        cur.execute("SELECT phone_number, last_inbound_at, last_message_text, last_outbound_at, created_at, updated_at FROM whatsapp_sessions WHERE phone_number = %s;" if is_pg else "SELECT phone_number, last_inbound_at, last_message_text, last_outbound_at, created_at, updated_at FROM whatsapp_sessions WHERE phone_number = ?;", (phone,))
        row = cur.fetchone()
        return _row_to_session(row) if row else {}
    finally:
        cur.close()
        conn.close()


def record_whatsapp_outbound(phone_number: str, timestamp: Optional[float] = None) -> None:
    """Updates last_outbound_at timestamp for a session."""
    import time
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    now_ts = timestamp if timestamp is not None else time.time()
    now_iso = datetime.now().isoformat()
    phone = phone_number.strip()
    try:
        sql = "UPDATE whatsapp_sessions SET last_outbound_at = %s, updated_at = %s WHERE phone_number = %s;" if is_pg else "UPDATE whatsapp_sessions SET last_outbound_at = ?, updated_at = ? WHERE phone_number = ?;"
        cur.execute(sql, (now_ts, now_iso, phone))
        if not is_pg:
            conn.commit()
    finally:
        cur.close()
        conn.close()


def get_whatsapp_session(phone_number: str) -> Optional[dict]:
    """Retrieve WhatsApp session record by phone number."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    phone = phone_number.strip()
    candidates = [phone]
    if phone.startswith("whatsapp:"):
        candidates.append(phone[len("whatsapp:"):])
    else:
        candidates.append(f"whatsapp:{phone}")

    try:
        for c in candidates:
            sql = "SELECT phone_number, last_inbound_at, last_message_text, last_outbound_at, created_at, updated_at FROM whatsapp_sessions WHERE phone_number = %s;" if is_pg else "SELECT phone_number, last_inbound_at, last_message_text, last_outbound_at, created_at, updated_at FROM whatsapp_sessions WHERE phone_number = ?;"
            cur.execute(sql, (c,))
            row = cur.fetchone()
            if row:
                return _row_to_session(row)
        return None
    finally:
        cur.close()
        conn.close()


def is_inside_24h_window(phone_number: str, now_ts: Optional[float] = None) -> bool:
    """
    Returns True if the customer sent an inbound message within the last 24 hours.
    Otherwise False (meaning a pre-approved template is required).
    """
    import time
    sess = get_whatsapp_session(phone_number)
    if not sess or not sess.get("last_inbound_at"):
        return False
    current_time = now_ts if now_ts is not None else time.time()
    elapsed = current_time - sess["last_inbound_at"]
    return 0 <= elapsed <= (24 * 3600)


def get_next_order_id() -> str:
    """Generate next sequential order ID (e.g. O0004)."""
    orders = get_orders()
    max_num = 0
    for o in orders:
        oid = o.get("id", "")
        if oid.startswith("O"):
            try:
                num = int(oid[1:])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    return f"O{max_num + 1:04d}"


def get_next_reservation_id() -> str:
    """Generate next sequential reservation ID (e.g. R0004)."""
    res = get_reservations()
    max_num = 0
    for r in res:
        rid = r.get("id", "")
        if rid.startswith("R"):
            try:
                num = int(rid[1:])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    return f"R{max_num + 1:04d}"


# Run initialization on import
init_db()
