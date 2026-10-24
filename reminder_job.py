"""
Booking reminder job for Amverio (The Copper Fork).

Finds upcoming CONFIRMED reservations within the reminder window (default: 3 hours)
that have not yet received a reminder, and delivers a WhatsApp reminder:
- Uses friendly free-form text if within the customer's 24-hour service window.
- Uses the pre-approved 'booking_reminder' template if outside the 24-hour window.
- Sends through Twilio by default, or the direct Meta Cloud API when WHATSAPP_PROVIDER=meta.
- Marks the reservation as notified to prevent duplicate reminders.

Usage:
    python reminder_job.py [--hours 3] [--dry-run]
"""

import sys
import os
import argparse
import logging
from datetime import datetime
from typing import Optional, Any

import db
import whatsapp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("amverio.reminder_job")


def _get_sender(client: Optional[Any]):
    """
    Picks the outbound provider. WHATSAPP_PROVIDER=meta uses the direct Meta Cloud API
    (`client` is then an optional HTTP object for tests); anything else keeps the
    Twilio path (`client` is then an optional Twilio client).
    """
    provider = os.environ.get("WHATSAPP_PROVIDER", "twilio").strip().lower()
    if provider == "meta":
        import meta_whatsapp
        return lambda **kw: meta_whatsapp.send_whatsapp(http=client, **kw)
    return lambda **kw: whatsapp.send_whatsapp(client=client, **kw)


def run_booking_reminders(
    hours_ahead: float = 3.0,
    dry_run: bool = False,
    now_dt: Optional[datetime] = None,
    client: Optional[Any] = None,
) -> list[dict]:
    """
    Scans the database for upcoming reservations due within hours_ahead,
    sends WhatsApp reminders respecting the 24-hour window policy,
    and updates the database.

    Returns:
        list[dict]: Summary of processed reminders.
    """
    ref_dt = now_dt or datetime.now()
    log.info(
        "Scanning for booking reminders due within %.1f hours of %s (dry_run=%s)",
        hours_ahead, ref_dt.strftime("%Y-%m-%d %H:%M"), dry_run
    )

    due_reservations = db.get_due_reminders(hours_ahead=hours_ahead, reference_dt=ref_dt)
    log.info("Found %d reservation(s) due for reminders.", len(due_reservations))

    send = _get_sender(client)
    results = []
    for res in due_reservations:
        res_id = res.get("id")
        customer_name = res.get("name", "Guest")
        phone_raw = res.get("phone", "")
        party_size = str(res.get("party_size", 2))
        res_time = res.get("time", "")

        try:
            whatsapp_to = whatsapp.normalize_whatsapp_number(phone_raw)
        except Exception as e:
            log.warning("Invalid phone number '%s' for reservation %s: %s", phone_raw, res_id, e)
            results.append({
                "reservation_id": res_id,
                "status": "skipped_invalid_phone",
                "error": str(e),
            })
            continue

        inside_window = db.is_inside_24h_window(whatsapp_to, now_ts=ref_dt.timestamp())
        log.info(
            "Processing reservation %s for %s (%s) — 24h window active: %s",
            res_id, customer_name, whatsapp_to, inside_window
        )

        try:
            if inside_window:
                # Inside 24h window -> free-form conversational reminder
                body_text = (
                    f"Hi {customer_name}, friendly reminder that your table for {party_size} "
                    f"at The Copper Fork is booked for today at {res_time}. "
                    f"We look forward to welcoming you! Need to adjust? Just let us know."
                )
                dispatch_res = send(
                    to=whatsapp_to,
                    text=body_text,
                    dry_run=dry_run,
                    now_ts=ref_dt.timestamp(),
                )
                msg_type = "free_text"
            else:
                # Outside 24h window -> pre-approved Meta/Twilio template
                template_vars = {
                    "1": customer_name,
                    "2": party_size,
                    "3": res_time,
                    "4": "The Copper Fork",
                }
                dispatch_res = send(
                    to=whatsapp_to,
                    template="booking_reminder",
                    variables=template_vars,
                    dry_run=dry_run,
                    now_ts=ref_dt.timestamp(),
                )
                msg_type = "template"

            if not dry_run:
                db.mark_reservation_reminder_sent(res_id, sent_at=ref_dt.isoformat())

            results.append({
                "reservation_id": res_id,
                "recipient": whatsapp_to,
                "name": customer_name,
                "party_size": party_size,
                "time": res_time,
                "type": msg_type,
                "inside_window": inside_window,
                "status": "sent" if not dry_run else "dry_run",
                "dispatch": dispatch_res,
            })
            log.info("Reminder successfully dispatched for reservation %s (%s)", res_id, msg_type)

        except Exception as e:
            log.exception("Failed to dispatch reminder for reservation %s: %s", res_id, e)
            results.append({
                "reservation_id": res_id,
                "recipient": whatsapp_to,
                "status": "error",
                "error": str(e),
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="Amverio WhatsApp Booking Reminder Job")
    parser.add_argument(
        "--hours",
        type=float,
        default=3.0,
        help="Hours ahead to scan for reservations (default: 3.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without sending live WhatsApp messages or updating DB",
    )
    args = parser.parse_args()

    results = run_booking_reminders(hours_ahead=args.hours, dry_run=args.dry_run)
    print("\n=======================================================")
    print(f"BOOKING REMINDER RUN SUMMARY ({len(results)} processed)")
    print("=======================================================")
    for r in results:
        status = r.get("status")
        rid = r.get("reservation_id")
        mtype = r.get("type", "unknown")
        name = r.get("name", "")
        recipient = r.get("recipient", "")
        print(f"- [{status.upper()}] Reservation {rid} -> {name} ({recipient}) via {mtype}")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
