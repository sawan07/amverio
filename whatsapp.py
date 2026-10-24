"""
WhatsApp messaging layer with Meta/Twilio 24-hour customer service window enforcement
and Content API template messaging support.

Meta / WhatsApp Policy:
- Within 24 hours of customer's last message: Free-form text and templates are permitted.
- Outside 24 hours of customer's last message: ONLY pre-approved templates are permitted.
  Free-form text is strictly prohibited and refused with WhatsAppWindowError.
"""

import os
import re
import json
import logging
from typing import Optional, Any, Union
from twilio.rest import Client

import db

log = logging.getLogger("amverio.whatsapp")

# Default Twilio WhatsApp Sandbox number
DEFAULT_WHATSAPP_FROM = "whatsapp:+14155238886"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WhatsAppError(Exception):
    """Base exception for WhatsApp messaging errors."""
    pass


class WhatsAppWindowError(WhatsAppError):
    """Raised when attempting to send free-form text outside the 24-hour customer window."""
    pass


class WhatsAppTemplateError(WhatsAppError):
    """Raised when an unknown, unapproved, or malformed template is requested."""
    pass


class WhatsAppDeliveryError(WhatsAppError):
    """Raised when message dispatch fails at the Twilio API layer."""
    pass


# ---------------------------------------------------------------------------
# Pre-approved Templates Configuration
# ---------------------------------------------------------------------------
# Twilio Content API template SIDs (starts with 'HX...').
# Environment variables allow overriding each SID when registered in production.
# Sandbox pre-approved template: 'HXb5b62575e6e4ff6129ad7c8efe1f983e'

TEMPLATES = {
    "booking_confirmation": {
        "name": "booking_confirmation",
        "category": "UTILITY",
        "content_sid": os.environ.get(
            "TWILIO_TEMPLATE_BOOKING_CONFIRMATION_SID",
            "HXb5b62575e6e4ff6129ad7c8efe1f983e",
        ),
        "variables": ["1", "2", "3", "4"],
        "variable_names": ["customer_name", "party_size", "date_time", "reservation_id"],
        "body": "Hi {{1}}, your table for {{2}} at The Copper Fork is confirmed for {{3}}. Your booking reference is {{4}}. To change or cancel, reply to this message.",
        "sample_variables": {
            "1": "Alex Morgan",
            "2": "4",
            "3": "Friday, 23 Oct at 19:00",
            "4": "R0015",
        },
    },
    "booking_reminder": {
        "name": "booking_reminder",
        "category": "UTILITY",
        "content_sid": os.environ.get(
            "TWILIO_TEMPLATE_BOOKING_REMINDER_SID",
            "HXb5b62575e6e4ff6129ad7c8efe1f983e",
        ),
        "variables": ["1", "2", "3", "4"],
        "variable_names": ["customer_name", "party_size", "time", "restaurant_name"],
        "body": "Hi {{1}}, this is a friendly reminder that your table for {{2}} at {{4}} is booked for today at {{3}}. We look forward to seeing you! Need to adjust? Reply directly to this message.",
        "sample_variables": {
            "1": "Sarah Jenkins",
            "2": "4",
            "3": "19:00",
            "4": "The Copper Fork",
        },
    },
    "order_ready": {
        "name": "order_ready",
        "category": "UTILITY",
        "content_sid": os.environ.get(
            "TWILIO_TEMPLATE_ORDER_READY_SID",
            "HXb5b62575e6e4ff6129ad7c8efe1f983e",
        ),
        "variables": ["1", "2", "3"],
        "variable_names": ["customer_name", "order_id", "order_type"],
        "body": "Hi {{1}}, great news! Your order #{{2}} is ready for {{3}} at The Copper Fork. Thank you for dining with us!",
        "sample_variables": {
            "1": "Sam Lee",
            "2": "O0012",
            "3": "pickup",
        },
    },
    "booking_cancelled": {
        "name": "booking_cancelled",
        "category": "UTILITY",
        "content_sid": os.environ.get(
            "TWILIO_TEMPLATE_BOOKING_CANCELLED_SID",
            "HXb5b62575e6e4ff6129ad7c8efe1f983e",
        ),
        "variables": ["1", "2", "3"],
        "variable_names": ["customer_name", "date_time", "reservation_id"],
        "body": "Hi {{1}}, your booking #{{3}} for {{2}} at The Copper Fork has been cancelled. If you'd like to reserve another time, just send us a message.",
        "sample_variables": {
            "1": "Jordan",
            "2": "tomorrow at 18:00",
            "3": "R0016",
        },
    },
}


# ---------------------------------------------------------------------------
# Text formatting helpers (shared by the Twilio and Meta Cloud API paths)
# ---------------------------------------------------------------------------

def format_for_whatsapp(text: str) -> str:
    """
    Adapts standard Markdown text to WhatsApp-native formatting:
    - Markdown bold **bold** -> *bold* (WhatsApp uses single asterisks for bold)
    - Markdown headers ### Header -> *Header*
    - Markdown links [Label](url) -> Label: url
    """
    if not text:
        return ""
    # Convert markdown links [Label](URL) -> Label: URL
    formatted = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\1: \2", text)
    # Convert markdown headers: ### Title -> *Title*
    formatted = re.sub(r"(?:^|(?<=\n)|(?<=\s))#{1,6}\s*(.+?)(?=\n|$)", r"*\1*", formatted)
    # Convert **bold** -> *bold*
    formatted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", formatted)
    return formatted.strip()


def split_message(text: str, max_length: int = 1500) -> list[str]:
    """
    Splits replies longer than max_length into conversational chunks,
    preferring paragraph breaks, newlines, sentence ends, or spaces.
    """
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_length:
        split_idx = remaining.rfind("\n\n", 0, max_length)
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = remaining.rfind("\n", 0, max_length)
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = remaining.rfind(". ", 0, max_length)
            if split_idx != -1:
                split_idx += 1
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = remaining.rfind(" ", 0, max_length)
        if split_idx == -1:
            split_idx = max_length

        chunk = remaining[:split_idx].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_idx:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def normalize_whatsapp_number(phone: str) -> str:
    """
    Normalizes any customer phone string into E.164 with whatsapp: prefix.
    Examples:
        '07123456789'           -> 'whatsapp:+447123456789'
        '+44 7123 456789'       -> 'whatsapp:+447123456789'
        'whatsapp:+447123456789'-> 'whatsapp:+447123456789'
    """
    if not phone:
        raise ValueError("Phone number cannot be empty.")
    n = phone.strip()
    if n.startswith("whatsapp:"):
        n = n[len("whatsapp:"):]
    n = n.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if n.startswith("00"):
        n = "+" + n[2:]
    elif n.startswith("07") and len(n) == 11:
        n = "+44" + n[1:]
    elif not n.startswith("+"):
        n = "+" + n
    return f"whatsapp:{n}"


def get_template_info(template_name_or_sid: str) -> Optional[dict]:
    """Retrieve template definition by name or ContentSid."""
    if template_name_or_sid in TEMPLATES:
        return TEMPLATES[template_name_or_sid]
    for tmpl in TEMPLATES.values():
        if tmpl["content_sid"] == template_name_or_sid:
            return tmpl
    return None


def list_templates() -> dict:
    """Returns the full catalog of registered WhatsApp templates."""
    return TEMPLATES


def render_template_preview(template_name: str, variables: dict) -> str:
    """Renders a human-readable preview of a template with provided variables."""
    tmpl = get_template_info(template_name)
    if not tmpl:
        raise WhatsAppTemplateError(f"Unknown template: {template_name}")
    text = tmpl["body"]
    for k, v in variables.items():
        text = text.replace(f"{{{{{k}}}}}", str(v))
    return text


def get_twilio_client() -> Client:
    """Initializes Twilio client using environment credentials."""
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid or not auth_token:
        raise WhatsAppDeliveryError(
            "Twilio credentials missing. Please set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN."
        )
    return Client(account_sid, auth_token)


def send_whatsapp(
    to: str,
    text: Optional[str] = None,
    template: Optional[str] = None,
    variables: Optional[dict] = None,
    client: Optional[Any] = None,
    from_number: Optional[str] = None,
    dry_run: bool = False,
    now_ts: Optional[float] = None,
) -> dict:
    """
    Sends an outbound WhatsApp message enforcing Meta's 24-hour customer service window:

    1. Inside 24h window (customer messaged recently):
       - Free-form text is permitted.
       - Templates are also permitted.
    2. Outside 24h window (or first business-initiated contact):
       - Free-form text is STRICTLY REFUSED with WhatsAppWindowError.
       - ONLY pre-approved templates (ContentSid + ContentVariables) are permitted.

    Parameters:
        to: Recipient phone number (e.g. '+447123456789' or 'whatsapp:+447123456789')
        text: Free-form text body (only valid within 24-hour window)
        template: Template name (e.g. 'booking_reminder') or ContentSid ('HX...')
        variables: Dictionary mapping variable positions (e.g. {"1": "Alex", "2": "4"})
        client: Optional Twilio Client instance (for testing/mocking)
        from_number: Sender WhatsApp address (defaults to TWILIO_WHATSAPP_FROM)
        dry_run: If True, validates rules and returns simulated delivery without calling API
        now_ts: Optional reference timestamp (useful for deterministic tests)

    Returns:
        dict: Message dispatch metadata (sid, to, from, status, type, inside_window)

    Raises:
        ValueError: Neither text nor template provided.
        WhatsAppWindowError: Free-form text attempted outside 24-hour customer window.
        WhatsAppTemplateError: Template name or ContentSid is unapproved / invalid.
        WhatsAppDeliveryError: Twilio API failure.
    """
    if not text and not template:
        raise ValueError("Either 'text' or 'template' must be provided.")

    to_normalized = normalize_whatsapp_number(to)
    from_normalized = from_number or os.environ.get("TWILIO_WHATSAPP_FROM", DEFAULT_WHATSAPP_FROM)
    inside_window = db.is_inside_24h_window(to_normalized, now_ts=now_ts)

    # -----------------------------------------------------------------------
    # Case A: Template Message (Valid both inside and outside 24h window)
    # -----------------------------------------------------------------------
    if template:
        tmpl_def = get_template_info(template)
        content_sid = None
        if tmpl_def:
            content_sid = tmpl_def["content_sid"]
        elif template.startswith("HX"):
            content_sid = template
        else:
            msg = (
                f"Unknown WhatsApp template: '{template}'. "
                f"Available registered templates: {list(TEMPLATES.keys())}"
            )
            log.error(msg)
            raise WhatsAppTemplateError(msg)

        var_payload = {str(k): str(v) for k, v in (variables or {}).items()}
        rendered_preview = tmpl_def["body"] if tmpl_def else f"[ContentSid {content_sid}]"
        for k, v in var_payload.items():
            rendered_preview = rendered_preview.replace(f"{{{{{k}}}}}", v)

        if dry_run:
            log.info(
                "[DRY RUN] WhatsApp template message to %s (ContentSid: %s): %s",
                to_normalized, content_sid, rendered_preview
            )
            db.record_whatsapp_outbound(to_normalized, timestamp=now_ts)
            return {
                "sid": "SM_mock_template_dry_run",
                "to": to_normalized,
                "from": from_normalized,
                "status": "dry_run",
                "type": "template",
                "content_sid": content_sid,
                "variables": var_payload,
                "inside_window": inside_window,
                "preview": rendered_preview,
            }

        api_client = client or get_twilio_client()
        try:
            msg_obj = api_client.messages.create(
                to=to_normalized,
                from_=from_normalized,
                content_sid=content_sid,
                content_variables=json.dumps(var_payload),
            )
            db.record_whatsapp_outbound(to_normalized, timestamp=now_ts)
            log.info(
                "WhatsApp template message sent to %s (SID: %s, ContentSid: %s)",
                to_normalized, msg_obj.sid, content_sid
            )
            return {
                "sid": msg_obj.sid,
                "to": to_normalized,
                "from": from_normalized,
                "status": getattr(msg_obj, "status", "sent"),
                "type": "template",
                "content_sid": content_sid,
                "variables": var_payload,
                "inside_window": inside_window,
                "preview": rendered_preview,
            }
        except Exception as e:
            log.exception("Twilio WhatsApp template delivery failed to %s: %s", to_normalized, e)
            raise WhatsAppDeliveryError(f"Failed to deliver WhatsApp template: {e}") from e

    # -----------------------------------------------------------------------
    # Case B: Free-Form Text Message (REQUIRES 24-HOUR CUSTOMER WINDOW)
    # -----------------------------------------------------------------------
    if not inside_window:
        err_msg = (
            f"Cannot send free-form text to '{to_normalized}'. "
            f"Customer is outside the 24-hour service window. "
            f"WhatsApp policy prohibits business-initiated free text; a pre-approved template must be used."
        )
        log.error("Rejecting WhatsApp dispatch: %s", err_msg)
        raise WhatsAppWindowError(err_msg)

    if dry_run:
        log.info("[DRY RUN] WhatsApp free-form text to %s: %s", to_normalized, text)
        db.record_whatsapp_outbound(to_normalized, timestamp=now_ts)
        return {
            "sid": "SM_mock_text_dry_run",
            "to": to_normalized,
            "from": from_normalized,
            "status": "dry_run",
            "type": "text",
            "body": text,
            "inside_window": True,
        }

    api_client = client or get_twilio_client()
    try:
        msg_obj = api_client.messages.create(
            to=to_normalized,
            from_=from_normalized,
            body=text,
        )
        db.record_whatsapp_outbound(to_normalized, timestamp=now_ts)
        log.info("WhatsApp free-form text sent to %s (SID: %s)", to_normalized, msg_obj.sid)
        return {
            "sid": msg_obj.sid,
            "to": to_normalized,
            "from": from_normalized,
            "status": getattr(msg_obj, "status", "sent"),
            "type": "text",
            "body": text,
            "inside_window": True,
        }
    except Exception as e:
        log.exception("Twilio WhatsApp text delivery failed to %s: %s", to_normalized, e)
        raise WhatsAppDeliveryError(f"Failed to deliver WhatsApp message: {e}") from e
