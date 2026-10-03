"""
The fundraising agent's tool layer -- same shape as the restaurant domain's
tools.py: a small set of boring, predictable functions the model can call,
each returning a plain dict. Keep these boring: the model should never need
to guess what happened.
"""

import re
from fundraising_data import (
    ORG, CAMPAIGNS, CAMPAIGNS_BY_ID, DONATIONS, GIFT_AID_RATE,
    next_donation_id,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

VALID_FREQUENCIES = ("one_off", "monthly")
VALID_DEDICATIONS = ("none", "in_memory_of", "in_honor_of", "on_behalf_of")


def _is_valid_email(email: str) -> bool:
    """
    Loose but real format check -- not a deliverability check. Just rejects
    obviously-wrong input (missing @, no domain) before a donation/receipt
    gets created, same role _is_valid_uk_phone plays for the restaurant
    domain's bookings/orders.
    """
    if not email or not isinstance(email, str):
        return False
    return bool(_EMAIL_RE.match(email.strip()))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def get_campaigns() -> dict:
    """List active fundraising campaigns/causes, with progress toward goal."""
    return {
        "organisation": ORG["name"],
        "currency": ORG["currency"],
        "campaigns": [
            {
                "id": c["id"],
                "name": c["name"],
                "description": c["description"],
                "goal": c["goal"],
                "raised": c["raised"],
            }
            for c in CAMPAIGNS
        ],
    }


def create_donation(
    amount: float,
    campaign_id: str,
    donor_name: str,
    donor_email: str,
    frequency: str = "one_off",
    anonymous: bool = False,
    gift_aid: bool = False,
    dedication_type: str = "none",
    dedication_name: str = "",
    message: str = "",
) -> dict:
    """
    Records a donation pledge if everything checks out. No real payment is
    taken through this tool -- it records intent, to be completed via a
    secure payment link/provider page afterward. Only call this once the
    donor has confirmed the full amount, frequency, cause, Gift Aid choice,
    and any dedication back to them.
    """
    if amount is None or amount <= 0:
        return {"success": False, "reason": "Donation amount must be greater than zero."}

    campaign = CAMPAIGNS_BY_ID.get(campaign_id)
    if not campaign:
        return {
            "success": False,
            "reason": f"Unknown campaign: {campaign_id}. Call get_campaigns for the current list.",
        }

    if frequency not in VALID_FREQUENCIES:
        return {"success": False, "reason": "frequency must be 'one_off' or 'monthly'."}

    if dedication_type not in VALID_DEDICATIONS:
        return {
            "success": False,
            "reason": "dedication_type must be one of: " + ", ".join(VALID_DEDICATIONS),
        }

    if dedication_type != "none" and not dedication_name:
        return {"success": False, "reason": "Please provide the name this donation is dedicated to."}

    if not donor_name:
        return {"success": False, "reason": "A name is needed to confirm the donation."}

    if not _is_valid_email(donor_email):
        return {
            "success": False,
            "reason": "That doesn't look like a valid email address. We need one to send a receipt.",
        }

    amount = round(float(amount), 2)
    gift_aid_bonus = round(amount * GIFT_AID_RATE, 2) if gift_aid else 0.0
    campaign["raised"] = round(campaign["raised"] + amount, 2)

    donation = {
        "id": next_donation_id(),
        "amount": amount,
        "frequency": frequency,
        "campaign_id": campaign["id"],
        "campaign_name": campaign["name"],
        "donor_name": donor_name,
        "donor_email": donor_email,
        "anonymous": bool(anonymous),
        "gift_aid": bool(gift_aid),
        "gift_aid_bonus": gift_aid_bonus,
        "dedication_type": dedication_type,
        "dedication_name": dedication_name,
        "message": message,
        "status": "PLEDGED",
        "payment": "pending -- a secure payment link would be sent next to complete this donation",
    }
    DONATIONS.append(donation)
    return {"success": True, "donation_id": donation["id"], **donation}


# ---------------------------------------------------------------------------
# Tool schemas -- same provider-neutral shape as the restaurant domain's
# TOOL_SCHEMAS; app.py/chat.py translate these into OpenAI's function format.
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "get_campaigns",
        "description": "Get the list of active fundraising campaigns/causes, with their goal and amount raised so far.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_donation",
        "description": (
            "Record a donation pledge. No real payment is taken through this tool -- "
            "the donor completes payment via a secure link sent afterward. Only call "
            "this once the donor has confirmed the amount, frequency, cause, Gift Aid "
            "choice, and any dedication."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Donation amount in GBP."},
                "campaign_id": {"type": "string"},
                "donor_name": {"type": "string"},
                "donor_email": {"type": "string"},
                "frequency": {"type": "string", "enum": ["one_off", "monthly"]},
                "anonymous": {
                    "type": "boolean",
                    "description": "True if the donor wants to stay anonymous publicly.",
                },
                "gift_aid": {
                    "type": "boolean",
                    "description": "True if the donor confirmed they're a UK taxpayer and wants Gift Aid claimed.",
                },
                "dedication_type": {
                    "type": "string",
                    "enum": ["none", "in_memory_of", "in_honor_of", "on_behalf_of"],
                },
                "dedication_name": {
                    "type": "string",
                    "description": "Name the donation is dedicated to, if dedication_type isn't 'none'.",
                },
                "message": {"type": "string", "description": "Optional personal message from the donor."},
            },
            "required": ["amount", "campaign_id", "donor_name", "donor_email"],
        },
    },
]

TOOL_FUNCTIONS = {
    "get_campaigns": lambda **kwargs: get_campaigns(),
    "create_donation": lambda **kwargs: create_donation(**kwargs),
}
