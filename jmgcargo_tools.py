"""
The JMG Cargo agent's tool layer -- same shape as tools.py and
fundraising_tools.py: small, boring functions that return plain dicts.

The price maths lives HERE, not in the model. The model gathers the
details (where, how heavy, how many boxes, what's inside, collection or
drop-off) and these functions work out the estimate, so the same inputs
always give the same number and the model never does arithmetic itself.
"""

import math
import re

from jmgcargo_data import (
    COMPANY, RATE_CARD, MIN_WEIGHT_KG, MAX_STANDARD_KG, ROUND_UP_TO_KG,
    VOLUMETRIC_DIVISOR, BANGLADESH_CITIES, ASIA_COUNTRIES, EUROPE_COUNTRIES,
    PROHIBITED_ITEMS, RESTRICTED_NOTE, QUOTE_REQUESTS, next_quote_id,
)
from tools import _is_valid_uk_phone
from fundraising_tools import _is_valid_email

_UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
_UK_NAMES = {"uk", "united kingdom", "england", "scotland", "wales", "northern ireland", "great britain", "britain"}

# Perishable food is only prohibited OUTSIDE the EU, so it isn't flagged
# for European destinations.
_NON_EU_ONLY = {"Perishable food outside the EU"}


def _norm(s) -> str:
    return (s or "").strip().lower()


def _resolve_region(country: str, city: str = "") -> str | None:
    """bangladesh / asia / europe / worldwide, or None for a UK destination."""
    c, ci = _norm(country), _norm(city)
    if c in _UK_NAMES:
        return None
    if c in ("bangladesh", "bd") or (not c and ci in BANGLADESH_CITIES):
        return "bangladesh"
    if c in ASIA_COUNTRIES:
        return "asia"
    if c in EUROPE_COUNTRIES:
        return "europe"
    return "worldwide"


def _find_prohibited(contents: str, region: str | None) -> list[str]:
    text = _norm(contents)
    if not text:
        return []
    hits = []
    for label, keywords in PROHIBITED_ITEMS:
        if region == "europe" and label in _NON_EU_ONLY:
            continue
        for kw in keywords:
            # Whole-word match (plurals allowed) so "fur" doesn't catch
            # "furniture" and "oil" doesn't catch "toilet".
            if re.search(r"\b" + re.escape(kw) + r"(s|es)?\b", text):
                hits.append(label)
                break
    return hits


def _chargeable_weight(total_weight_kg, parcels) -> tuple[float, float, float]:
    """
    Returns (actual_kg, volumetric_kg, chargeable_kg). Per parcel, the
    higher of actual vs volumetric weight is charged (when dimensions are
    given); the total is then rounded up to the next ROUND_UP_TO_KG.
    """
    actual = 0.0
    volumetric = 0.0
    charged = 0.0
    if parcels:
        for p in parcels:
            w = float(p.get("weight_kg") or 0)
            dims = [p.get("length_cm"), p.get("width_cm"), p.get("height_cm")]
            v = 0.0
            if all(d not in (None, "", 0) for d in dims):
                v = float(dims[0]) * float(dims[1]) * float(dims[2]) / VOLUMETRIC_DIVISOR
            actual += w
            volumetric += v
            charged += max(w, v)
    else:
        actual = float(total_weight_kg or 0)
        charged = actual

    charged = max(charged, MIN_WEIGHT_KG)
    charged = math.ceil(charged / ROUND_UP_TO_KG - 1e-9) * ROUND_UP_TO_KG
    return round(actual, 2), round(volumetric, 2), float(charged)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def get_service_info() -> dict:
    """Company details, services, published rates, opening hours, FAQs."""
    return {
        **COMPANY,
        "published_rates_from_per_kg": {v["label"]: v["from_per_kg"] for v in RATE_CARD.values()},
        "rates_note": "These are 'from' prices; JMG says prices might change daily. Final price is confirmed by the team.",
        "restricted_items_note": RESTRICTED_NOTE,
    }


def check_items(contents: str, destination_country: str = "", destination_city: str = "") -> dict:
    """Flag anything in a free-text contents description that JMG prohibits."""
    region = _resolve_region(destination_country, destination_city)
    hits = _find_prohibited(contents, region)
    return {
        "contents": contents,
        "possibly_prohibited": hits,
        "ok": not hits,
        "note": (
            "These look like items JMG cannot send. Ask the customer to confirm "
            "exactly what they are -- some (e.g. dry packaged food, dry-cell "
            "batteries) may be fine and the team will check."
            if hits else
            "Nothing obviously prohibited, but the team still checks every parcel. "
            "Remind the customer everything must be boxed."
        ),
        "restricted_items_note": RESTRICTED_NOTE,
    }


def estimate_quote(
    destination_country: str,
    destination_city: str = "",
    total_weight_kg: float | None = None,
    num_parcels: int = 1,
    parcels: list | None = None,
    pickup_required: bool = False,
    insurance: bool = False,
    express: bool = False,
) -> dict:
    """
    Works out an estimated starting price from the published per-kg rates.
    Either total_weight_kg, or a parcels list (weight + optional dimensions
    each), is needed.
    """
    region = _resolve_region(destination_country, destination_city)
    if region is None:
        return {
            "success": False,
            "reason": "JMG Cargo ships from the UK to other countries -- UK-to-UK delivery isn't one of the listed services. Suggest calling 020 7247 8878 to ask.",
        }

    if not parcels and (total_weight_kg is None or float(total_weight_kg) <= 0):
        return {"success": False, "reason": "Need the approximate total weight in kg (or each parcel's weight)."}
    if parcels and any(float(p.get("weight_kg") or 0) <= 0 for p in parcels):
        return {"success": False, "reason": "Each parcel needs a weight greater than zero."}

    actual, volumetric, chargeable = _chargeable_weight(total_weight_kg, parcels)
    rate = RATE_CARD[region]["from_per_kg"]
    estimate = round(chargeable * rate, 2)
    n_parcels = len(parcels) if parcels else int(num_parcels or 1)

    to_confirm = []
    if pickup_required:
        to_confirm.append("collection charge (if any)")
    if insurance:
        to_confirm.append("insurance cost")
    if express:
        to_confirm.append("express delivery surcharge")

    notes = ["Estimate based on JMG's published 'from' rate -- prices can change daily, so the team confirms the final price."]
    if volumetric > actual:
        notes.append(f"Parcels are bulky for their weight, so the volumetric weight ({volumetric}kg) is used instead of the actual weight ({actual}kg).")
    if chargeable > MAX_STANDARD_KG:
        notes.append(f"Over {MAX_STANDARD_KG}kg counts as a large shipment -- JMG arranges these specially and may offer a better rate.")

    return {
        "success": True,
        "destination": ", ".join(x for x in [destination_city, destination_country] if x),
        "region": RATE_CARD[region]["label"],
        "rate_from_per_kg": rate,
        "num_parcels": n_parcels,
        "actual_weight_kg": actual,
        "volumetric_weight_kg": volumetric if parcels else None,
        "chargeable_weight_kg": chargeable,
        "estimated_from_gbp": estimate,
        "extras_to_be_confirmed": to_confirm,
        "notes": notes,
    }


def submit_quote_request(
    customer_name: str,
    email: str,
    destination_country: str,
    contents: str,
    destination_city: str = "",
    phone: str = "",
    total_weight_kg: float | None = None,
    num_parcels: int = 1,
    parcels: list | None = None,
    pickup_required: bool = False,
    pickup_postcode: str = "",
    insurance: bool = False,
    express: bool = False,
    contents_confirmed_ok: bool = False,
    message: str = "",
) -> dict:
    """
    Records a quote request for the JMG team to confirm -- the same thing
    their website's "Get Free Quote" form collects, plus the estimate.
    The estimate is recalculated here rather than trusted from the model.
    """
    if not customer_name or not customer_name.strip():
        return {"success": False, "reason": "A name is needed so the team knows who the quote is for."}
    if not _is_valid_email(email):
        return {"success": False, "reason": "That doesn't look like a valid email address -- the quote is sent by email."}
    if phone and not _is_valid_uk_phone(phone):
        return {"success": False, "reason": "That doesn't look like a valid UK phone number. It's optional -- leave it out or correct it."}
    if not contents or not contents.strip():
        return {"success": False, "reason": "Need a short description of what's being sent."}
    if pickup_required and not _UK_POSTCODE_RE.match((pickup_postcode or "").strip()):
        return {"success": False, "reason": "For a collection, a valid UK postcode is needed."}

    est = estimate_quote(
        destination_country, destination_city, total_weight_kg, num_parcels,
        parcels, pickup_required, insurance, express,
    )
    if not est.get("success"):
        return est

    region = _resolve_region(destination_country, destination_city)
    flagged = _find_prohibited(contents, region)
    if flagged and not contents_confirmed_ok:
        return {
            "success": False,
            "reason": "The contents may include items JMG can't send. Check with the customer first; only resubmit with contents_confirmed_ok=true once they've confirmed these items are removed or are actually allowed.",
            "possibly_prohibited": flagged,
        }

    request = {
        "id": next_quote_id(),
        "customer_name": customer_name.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "destination": est["destination"],
        "region": est["region"],
        "num_parcels": est["num_parcels"],
        "chargeable_weight_kg": est["chargeable_weight_kg"],
        "estimated_from_gbp": est["estimated_from_gbp"],
        "contents": contents.strip(),
        "flagged_items_customer_confirmed": flagged,
        "pickup_required": bool(pickup_required),
        "pickup_postcode": pickup_postcode.strip().upper() if pickup_required else "",
        "insurance": bool(insurance),
        "express": bool(express),
        "message": message,
        "status": "QUOTE_REQUESTED",
    }
    QUOTE_REQUESTS.append(request)
    return {
        "success": True,
        "reference": request["id"],
        **request,
        "next_step": "The JMG team will email the confirmed price (open Mon-Sat 10am-7pm). Urgent? Call 020 7247 8878.",
    }


# ---------------------------------------------------------------------------
# Tool schemas -- provider-neutral; app.py/chat.py translate to OpenAI format.
# ---------------------------------------------------------------------------

_PARCELS_SCHEMA = {
    "type": "array",
    "description": "Optional per-parcel detail. Use when the customer gives individual box weights or dimensions; otherwise use total_weight_kg + num_parcels.",
    "items": {
        "type": "object",
        "properties": {
            "weight_kg": {"type": "number"},
            "length_cm": {"type": "number"},
            "width_cm": {"type": "number"},
            "height_cm": {"type": "number"},
        },
        "required": ["weight_kg"],
    },
}

_DEST_PROPS = {
    "destination_country": {"type": "string", "description": "Destination country, e.g. 'Bangladesh'."},
    "destination_city": {"type": "string", "description": "Destination city/town if known, e.g. 'Sylhet'."},
}

TOOL_SCHEMAS = [
    {
        "name": "get_service_info",
        "description": "Get JMG Cargo's services, published 'from' rates per kg, opening hours, address, contact details, payment methods and FAQ answers.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_items",
        "description": "Check a description of the parcel contents against JMG's prohibited items list.",
        "input_schema": {
            "type": "object",
            "properties": {"contents": {"type": "string"}, **_DEST_PROPS},
            "required": ["contents"],
        },
    },
    {
        "name": "estimate_quote",
        "description": "Calculate an estimated starting price for a shipment from JMG's published rates. Always use this for any price -- never calculate prices yourself.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_DEST_PROPS,
                "total_weight_kg": {"type": "number", "description": "Approximate total weight of all parcels in kg."},
                "num_parcels": {"type": "integer"},
                "parcels": _PARCELS_SCHEMA,
                "pickup_required": {"type": "boolean"},
                "insurance": {"type": "boolean"},
                "express": {"type": "boolean"},
            },
            "required": ["destination_country"],
        },
    },
    {
        "name": "submit_quote_request",
        "description": "Send the quote request to the JMG team, who email back a confirmed price. Only call after the customer has confirmed the summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string", "description": "Optional UK phone number."},
                **_DEST_PROPS,
                "contents": {"type": "string", "description": "What's in the parcels."},
                "total_weight_kg": {"type": "number"},
                "num_parcels": {"type": "integer"},
                "parcels": _PARCELS_SCHEMA,
                "pickup_required": {"type": "boolean"},
                "pickup_postcode": {"type": "string", "description": "UK postcode for collection, required if pickup_required."},
                "insurance": {"type": "boolean"},
                "express": {"type": "boolean"},
                "contents_confirmed_ok": {
                    "type": "boolean",
                    "description": "Set true ONLY if check_items flagged something and the customer has confirmed it's removed or actually allowed.",
                },
                "message": {"type": "string", "description": "Any extra info from the customer."},
            },
            "required": ["customer_name", "email", "destination_country", "contents"],
        },
    },
]

TOOL_FUNCTIONS = {
    "get_service_info": lambda **kwargs: get_service_info(),
    "check_items": lambda **kwargs: check_items(**kwargs),
    "estimate_quote": lambda **kwargs: estimate_quote(**kwargs),
    "submit_quote_request": lambda **kwargs: submit_quote_request(**kwargs),
}
