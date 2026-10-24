"""
Direct Meta WhatsApp Cloud API integration (graph.facebook.com), no middleman.

What lives here
- Webhook helpers: the GET verification handshake and the HMAC-SHA256 signature
  check (X-Hub-Signature-256, signed with the Meta App Secret), plus a parser that
  turns Meta's nested webhook JSON into a flat list of inbound messages.
- Outbound client: send_whatsapp() / send_reply() call
  POST https://graph.facebook.com/{version}/{phone_number_id}/messages and enforce
  the same 24-hour customer-service-window rule as whatsapp.py (Twilio):
    * inside the window -> free-form text or a template
    * outside the window -> approved templates ONLY (text raises WhatsAppWindowError)

Configuration (environment variables, read at call time):
    META_WA_PHONE_NUMBER_ID      the sending number's Phone Number ID
    META_WA_ACCESS_TOKEN         permanent System User token (never a 24h test token in prod)
    META_WA_VERIFY_TOKEN         any secret string you also type into Meta's webhook setup
    META_APP_SECRET              the Meta App Secret (signs inbound webhooks)
    META_WA_BUSINESS_ACCOUNT_ID  WhatsApp Business Account ID (used by docs/ops, not per message)
    META_GRAPH_API_VERSION       optional, default v23.0 (v20.0 expired on 24 Sep 2026)
    META_WA_TEMPLATE_LANG        optional, default en_GB (language the templates were approved in)
"""

import os
import hmac
import hashlib
import logging
import time
from typing import Optional, Any

import httpx

import db
from whatsapp import (
    WhatsAppWindowError,
    WhatsAppTemplateError,
    WhatsAppDeliveryError,
    TEMPLATES,
    get_template_info,
    normalize_whatsapp_number,
    format_for_whatsapp,
    split_message,
)

log = logging.getLogger("amverio.meta_whatsapp")

DEFAULT_GRAPH_API_VERSION = "v23.0"
DEFAULT_TEMPLATE_LANGUAGE = "en_GB"
REQUEST_TIMEOUT_SECONDS = 15
MAX_CHUNK_CHARS = 1500  # conversational chunk size (Meta's hard limit is 4096)

# Meta error code returned when free-form text is sent outside the 24h window.
ERR_REENGAGEMENT_WINDOW = 131047


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def graph_base_url() -> str:
    return f"https://graph.facebook.com/{_env('META_GRAPH_API_VERSION') or DEFAULT_GRAPH_API_VERSION}"


def is_configured() -> bool:
    """True when the credentials needed to SEND messages are present."""
    return bool(_env("META_WA_PHONE_NUMBER_ID") and _env("META_WA_ACCESS_TOKEN"))


# ---------------------------------------------------------------------------
# Webhook helpers
# ---------------------------------------------------------------------------

def verify_webhook_challenge(mode: Optional[str], token: Optional[str], challenge: Optional[str]) -> Optional[str]:
    """
    Meta's GET handshake: hub.mode=subscribe, hub.verify_token=<ours>, hub.challenge=<echo>.
    Returns the challenge string to echo back, or None if the request must be refused.
    """
    expected = _env("META_WA_VERIFY_TOKEN")
    if not expected:
        log.warning("Rejecting Meta webhook handshake: META_WA_VERIFY_TOKEN is not configured.")
        return None
    if mode != "subscribe" or not token or challenge is None:
        return None
    if hmac.compare_digest(token.encode(), expected.encode()):
        return challenge
    log.warning("Rejecting Meta webhook handshake: verify token mismatch.")
    return None


def verify_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """
    Validates X-Hub-Signature-256 ("sha256=<hex>") = HMAC-SHA256(app_secret, raw request body).
    Must be given the exact raw bytes Meta sent, not re-serialised JSON.
    """
    secret = _env("META_APP_SECRET")
    if not secret:
        log.warning("Rejecting Meta webhook: META_APP_SECRET is not configured.")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        log.warning("Rejecting Meta webhook: missing or malformed X-Hub-Signature-256 header.")
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    supplied = signature_header[len("sha256="):].strip().lower()
    if hmac.compare_digest(expected.encode(), supplied.encode("utf-8", "ignore")):
        return True
    log.warning("Rejecting Meta webhook: signature mismatch.")
    return False


def parse_inbound(payload: dict) -> list:
    """
    Flattens Meta's webhook JSON (entry[].changes[].value.messages[]) into a list of:
        {"message_id", "from", "name", "type", "text", "timestamp"}
    "text" is filled for plain text and for button / interactive replies, and is ""
    for media and anything else we cannot read. Delivery-status updates
    (value.statuses) carry no messages and are ignored.
    """
    inbound = []
    for entry in (payload or {}).get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {
                c.get("wa_id"): (c.get("profile") or {}).get("name", "")
                for c in (value.get("contacts") or [])
            }
            for m in value.get("messages") or []:
                mtype = m.get("type", "")
                text = ""
                if mtype == "text":
                    text = (m.get("text") or {}).get("body", "")
                elif mtype == "button":
                    text = (m.get("button") or {}).get("text", "")
                elif mtype == "interactive":
                    reply = m.get("interactive") or {}
                    text = (reply.get("button_reply") or reply.get("list_reply") or {}).get("title", "")
                try:
                    ts = float(m["timestamp"]) if m.get("timestamp") else None
                except (TypeError, ValueError):
                    ts = None
                inbound.append({
                    "message_id": m.get("id", ""),
                    "from": m.get("from", ""),
                    "name": names.get(m.get("from"), ""),
                    "type": mtype,
                    "text": (text or "").strip(),
                    "timestamp": ts,
                })
    return inbound


def inbound_timestamp(msg_ts: Optional[float]) -> float:
    """Message time from Meta, but never in the future (clock skew would break the 24h check)."""
    now = time.time()
    return min(msg_ts, now) if msg_ts else now


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------

def _clean_param(value: Any) -> str:
    # Template parameters may not contain newlines/tabs or runs of 4+ spaces.
    return " ".join(str(value).split())


def _post_message(payload: dict, http: Optional[Any] = None) -> dict:
    phone_number_id = _env("META_WA_PHONE_NUMBER_ID")
    token = _env("META_WA_ACCESS_TOKEN")
    if not phone_number_id or not token:
        raise WhatsAppDeliveryError(
            "Meta WhatsApp credentials missing. Please set META_WA_PHONE_NUMBER_ID and META_WA_ACCESS_TOKEN."
        )
    url = f"{graph_base_url()}/{phone_number_id}/messages"
    post = http.post if http is not None else httpx.post
    try:
        resp = post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as e:
        raise WhatsAppDeliveryError(f"Could not reach the Meta WhatsApp API: {e}") from e

    try:
        data = resp.json()
    except Exception:
        data = {}

    if resp.status_code >= 300:
        err = (data or {}).get("error") or {}
        code = err.get("code")
        detail = err.get("error_data", {}).get("details") if isinstance(err.get("error_data"), dict) else None
        message = f"Meta WhatsApp API error {resp.status_code} (code {code}): {err.get('message', 'unknown error')}"
        if detail:
            message += f" - {detail}"
        if code == ERR_REENGAGEMENT_WINDOW:
            raise WhatsAppWindowError(message)
        raise WhatsAppDeliveryError(message)
    return data or {}


def send_whatsapp(
    to: str,
    text: Optional[str] = None,
    template: Optional[str] = None,
    variables: Optional[dict] = None,
    http: Optional[Any] = None,
    dry_run: bool = False,
    now_ts: Optional[float] = None,
    language: Optional[str] = None,
) -> dict:
    """
    Sends an outbound WhatsApp message via the Meta Cloud API, enforcing the 24-hour window.

    Same contract as whatsapp.send_whatsapp (Twilio), so callers can swap providers:
      - text   -> only inside the 24-hour customer window, else WhatsAppWindowError
      - template (by name, e.g. 'booking_reminder') + variables ({"1": "Alex", ...})
                -> allowed any time; variables are sent in the template's positional order
      - http   -> optional object with .post(url, headers=, json=, timeout=) for tests
      - dry_run-> validates everything, calls nothing, records nothing

    Returns a dict: sid/message_id (wamid...), to, from, status, type, inside_window (+ preview).
    """
    if not text and not template:
        raise ValueError("Either 'text' or 'template' must be provided.")

    to_normalized = normalize_whatsapp_number(to)
    recipient = to_normalized[len("whatsapp:+"):]      # Meta wants digits: 447123456789
    sender = _env("META_WA_PHONE_NUMBER_ID")
    inside_window = db.is_inside_24h_window(to_normalized, now_ts=now_ts)

    # ----- Template (valid inside and outside the window) -----
    if template:
        tmpl = get_template_info(template)
        if not tmpl:
            msg = f"Unknown WhatsApp template: '{template}'. Available registered templates: {list(TEMPLATES.keys())}"
            log.error(msg)
            raise WhatsAppTemplateError(msg)

        supplied = {str(k): v for k, v in (variables or {}).items()}
        missing = [k for k in tmpl["variables"] if k not in supplied]
        if missing:
            raise WhatsAppTemplateError(
                f"Template '{tmpl['name']}' needs variables {tmpl['variables']}; missing {missing}."
            )
        ordered = [_clean_param(supplied[k]) for k in tmpl["variables"]]
        preview = tmpl["body"]
        for k in tmpl["variables"]:
            preview = preview.replace(f"{{{{{k}}}}}", _clean_param(supplied[k]))

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "template",
            "template": {
                "name": tmpl["name"],
                "language": {"code": language or _env("META_WA_TEMPLATE_LANG") or DEFAULT_TEMPLATE_LANGUAGE},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": v} for v in ordered]}
                ],
            },
        }
        result = {
            "to": to_normalized, "from": sender, "type": "template", "template": tmpl["name"],
            "variables": dict(zip(tmpl["variables"], ordered)), "inside_window": inside_window,
            "preview": preview,
        }
    # ----- Free-form text (needs the window) -----
    else:
        if not inside_window:
            err_msg = (
                f"Cannot send free-form text to '{to_normalized}'. Customer is outside the 24-hour service window. "
                f"WhatsApp policy prohibits business-initiated free text; a pre-approved template must be used."
            )
            log.error("Rejecting WhatsApp dispatch: %s", err_msg)
            raise WhatsAppWindowError(err_msg)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        result = {
            "to": to_normalized, "from": sender, "type": "text", "body": text, "inside_window": True,
        }

    if dry_run:
        log.info("[DRY RUN] Meta WhatsApp %s message to %s", result["type"], to_normalized)
        return {"sid": "wamid_dry_run", "message_id": "wamid_dry_run", "status": "dry_run", **result}

    data = _post_message(payload, http=http)
    wamid = ((data.get("messages") or [{}])[0]).get("id", "")
    db.record_whatsapp_outbound(to_normalized, timestamp=now_ts)
    log.info("Meta WhatsApp %s sent to %s (id: %s)", result["type"], to_normalized, wamid)
    return {"sid": wamid, "message_id": wamid, "status": "sent", **result}


def send_reply(to: str, text: str, http: Optional[Any] = None, now_ts: Optional[float] = None) -> list:
    """Formats an agent reply for WhatsApp, splits it into readable chunks, sends each one."""
    chunks = split_message(format_for_whatsapp(text), max_length=MAX_CHUNK_CHARS)
    return [send_whatsapp(to, text=chunk, http=http, now_ts=now_ts) for chunk in chunks]
