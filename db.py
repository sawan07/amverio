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


def _resolve_sqlite_path() -> str:
    """
    Where the SQLite file lives. Set AMVERIO_DB_PATH to put it on a persistent
    volume (e.g. /app/data/amverio.db in Docker/Coolify). Default: ./data/amverio.db
    next to this file. Ignored when DATABASE_URL points at PostgreSQL.
    """
    configured = os.environ.get("AMVERIO_DB_PATH", "").strip()
    path = configured or os.path.join(_here, "data", "amverio.db")
    return os.path.abspath(os.path.expanduser(path))


SQLITE_DB_PATH = _resolve_sqlite_path()

# Arbitrary constant used as the PostgreSQL advisory-lock key that serialises
# bookings and ID allocation (SQLite uses BEGIN IMMEDIATE for the same job).
_PG_LOCK_KEY = 7_204_117

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
    os.makedirs(os.path.dirname(SQLITE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # WAL: readers don't block the writer, and a crash mid-write can't
        # corrupt the file. busy_timeout makes concurrent writers wait, not fail.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
    except sqlite3.Error as e:  # e.g. a filesystem that can't do WAL
        log.warning("Could not enable WAL on %s: %s", SQLITE_DB_PATH, e)
    return conn


def _seed_enabled() -> bool:
    return os.environ.get("AMVERIO_SEED_DEMO_DATA", "1").strip().lower() not in ("0", "false", "no", "off")


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

        # Conversation history (so a restart doesn't make the agent forget a
        # customer mid-booking), ID counters, and a lookup index.
        text_id = "VARCHAR(128)" if is_pg else "TEXT"
        real_t = "DOUBLE PRECISION" if is_pg else "REAL"
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS conversations (
            session_id {text_id} PRIMARY KEY,
            domain {text_id} NOT NULL,
            messages TEXT NOT NULL,
            last_seen {real_t} NOT NULL,
            created_at {text_id} NOT NULL,
            updated_at {text_id} NOT NULL
        );
        """)
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS counters (
            name {text_id} PRIMARY KEY,
            value INTEGER NOT NULL
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reservations_table_date ON reservations (table_id, date);")
        if not is_pg:
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

        # Demo seed data (3 sample orders + 3 sample bookings) only goes into an
        # EMPTY database, and can be switched off for a real pilot with
        # AMVERIO_SEED_DEMO_DATA=0 so fake bookings never block real tables.
        if _seed_enabled():
            cur.execute("SELECT COUNT(*) FROM orders;")
            if cur.fetchone()[0] == 0:
                _seed_orders(cur, is_pg)
                if not is_pg:
                    conn.commit()

            cur.execute("SELECT COUNT(*) FROM reservations;")
            if cur.fetchone()[0] == 0:
                _seed_reservations(cur, is_pg)
                if not is_pg:
                    conn.commit()

        if is_pg:
            log.info("Database initialized successfully (engine=PostgreSQL)")
        else:
            log.info("Database initialized successfully (engine=SQLite, path=%s)", SQLITE_DB_PATH)
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


def _ph(sql: str, is_pg: bool) -> str:
    """Write queries with ? placeholders; convert to %s for PostgreSQL."""
    return sql.replace("?", "%s") if is_pg else sql


def _begin_exclusive(conn, cur, is_pg: bool) -> None:
    """
    Start a write transaction that other writers must wait for. This is what
    stops two simultaneous requests from double-booking a table or being handed
    the same order ID.
    """
    if is_pg:
        conn.autocommit = False
        cur.execute("SELECT pg_advisory_xact_lock(%s);", (_PG_LOCK_KEY,))
    else:
        cur.execute("BEGIN IMMEDIATE;")


def _allocate_id(cur, is_pg: bool, table: str, prefix: str) -> str:
    """
    Next sequential ID (O0004, R0007...). Must run inside _begin_exclusive.
    Uses max(existing ids, stored counter) + 1, so an ID is never reused even
    if the latest row is later deleted.
    """
    cur.execute(f"SELECT id FROM {table};")  # `table` is an internal constant
    max_num = 0
    for row in cur.fetchall():
        rid = str(row[0])
        if rid.startswith(prefix):
            try:
                max_num = max(max_num, int(rid[len(prefix):]))
            except ValueError:
                pass
    cur.execute(_ph("SELECT value FROM counters WHERE name = ?;", is_pg), (table,))
    row = cur.fetchone()
    counter = int(row[0]) if row else 0
    new_num = max(max_num, counter) + 1
    if row:
        cur.execute(_ph("UPDATE counters SET value = ? WHERE name = ?;", is_pg), (new_num, table))
    else:
        cur.execute(_ph("INSERT INTO counters (name, value) VALUES (?, ?);", is_pg), (table, new_num))
    return f"{prefix}{new_num:04d}"


def _next_id(table: str, prefix: str) -> str:
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        _begin_exclusive(conn, cur, is_pg)
        new_id = _allocate_id(cur, is_pg, table, prefix)
        conn.commit()
        return new_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def get_next_order_id() -> str:
    """Reserve and return the next sequential order ID (e.g. O0004). Safe under concurrency."""
    return _next_id("orders", "O")


def get_next_reservation_id() -> str:
    """Reserve and return the next sequential reservation ID (e.g. R0004). Safe under concurrency."""
    return _next_id("reservations", "R")


def add_reservation_if_free(res: dict, seating_minutes: int = 90) -> Optional[dict]:
    """
    Atomically insert a reservation only if its table is still free for the
    seating window. Returns the saved reservation (with an ID assigned if it
    had none), or None if the table was taken in the meantime.

    The check and the insert happen inside ONE exclusive transaction, so two
    simultaneous requests for the same table can never both succeed.
    """
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        _begin_exclusive(conn, cur, is_pg)
        new_start = datetime.strptime(f"{res['date']} {res['time']}", "%Y-%m-%d %H:%M")
        new_end = new_start + timedelta(minutes=seating_minutes)

        cur.execute(
            _ph("SELECT time FROM reservations WHERE table_id = ? AND date = ? AND status = 'CONFIRMED';", is_pg),
            (res["table_id"], res["date"]),
        )
        for row in cur.fetchall():
            try:
                other_start = datetime.strptime(f"{res['date']} {row[0]}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            other_end = other_start + timedelta(minutes=seating_minutes)
            if new_start < other_end and new_end > other_start:
                conn.rollback()
                return None

        saved = dict(res)
        if not saved.get("id"):
            saved["id"] = _allocate_id(cur, is_pg, "reservations", "R")
        saved.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
        cur.execute(
            _ph(
                "INSERT INTO reservations (id, table_id, date, time, party_size, name, phone, status, created_at, reminder_sent_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                is_pg,
            ),
            (
                saved["id"], saved["table_id"], saved["date"], saved["time"], int(saved["party_size"]),
                saved["name"], saved["phone"], saved["status"], saved["created_at"], saved.get("reminder_sent_at"),
            ),
        )
        conn.commit()
        return saved
    except Exception:
        conn.rollback()
        log.exception("Database error in add_reservation_if_free for table %s", res.get("table_id"))
        raise
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Conversation history persistence
# ---------------------------------------------------------------------------

def save_conversation(session_id: str, domain_id: str, messages: list, last_seen: Optional[float] = None) -> None:
    """Insert or update a conversation's full message history."""
    import time
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    now_iso = datetime.now().isoformat()
    try:
        cur.execute(
            _ph(
                "INSERT INTO conversations (session_id, domain, messages, last_seen, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (session_id) DO UPDATE SET "
                "domain = excluded.domain, messages = excluded.messages, "
                "last_seen = excluded.last_seen, updated_at = excluded.updated_at;",
                is_pg,
            ),
            (
                session_id, domain_id, json.dumps(messages, default=str),
                last_seen if last_seen is not None else time.time(), now_iso, now_iso,
            ),
        )
        if not is_pg:
            conn.commit()
    finally:
        cur.close()
        conn.close()


def load_conversation(session_id: str) -> Optional[dict]:
    """Return {"session_id", "domain", "messages", "last_seen"} or None."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            _ph("SELECT session_id, domain, messages, last_seen FROM conversations WHERE session_id = ?;", is_pg),
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        try:
            messages = json.loads(row[2])
        except Exception:
            log.warning("Conversation %s has unreadable history; ignoring it", session_id)
            return None
        return {"session_id": row[0], "domain": row[1], "messages": messages, "last_seen": float(row[3])}
    finally:
        cur.close()
        conn.close()


def delete_stale_conversations(cutoff_ts: float) -> int:
    """Delete conversations last used before cutoff_ts. Returns how many were removed."""
    is_pg = _is_postgres()
    conn = _get_connection()
    cur = conn.cursor()
    try:
        cur.execute(_ph("DELETE FROM conversations WHERE last_seen < ?;", is_pg), (cutoff_ts,))
        removed = cur.rowcount
        if not is_pg:
            conn.commit()
        return removed
    finally:
        cur.close()
        conn.close()


# Run initialization on import
init_db()
