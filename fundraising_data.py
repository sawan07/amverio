"""
In-memory demo data for the Amverio fundraising agent.

Same "logic first" demo pattern as the restaurant domain (data.py/tools.py):
an invented charity persona and in-memory campaigns/donations, so the
conversation + tool-calling flow can be proven out before this touches a
real donor database or a real payment provider (Stripe, GoCardless, etc.).

This is a separate domain, not a separate app -- see domain.py, which picks
between this and the restaurant domain's data.py/tools.py based on the
AMVERIO_DOMAIN environment variable. Nothing else about the deployment
changes.
"""

import itertools

# ---------------------------------------------------------------------------
# Organisation identity (invented demo persona -- swap freely before this
# represents a real charity, same role "The Copper Fork" plays for the
# restaurant domain)
# ---------------------------------------------------------------------------

ORG = {
    "name": "Bright Horizons Trust",
    "mission": "A UK community charity supporting people facing homelessness and disadvantaged young people.",
    "currency": "GBP",
    "registered_charity": "Demo persona -- not a real registered charity number.",
}

# ---------------------------------------------------------------------------
# Campaigns -- the "causes" a donor can give to. "goal" is None for an
# unrestricted/general fund that isn't working toward a fixed target.
# ---------------------------------------------------------------------------

CAMPAIGNS = [
    {
        "id": "WINTER25",
        "name": "Winter Shelter Appeal",
        "description": "Funds emergency overnight shelter, hot meals and warm clothing through the cold months.",
        "goal": 20000.00,
        "raised": 8450.00,
    },
    {
        "id": "YOUTH",
        "name": "Youth Mentoring Programme",
        "description": "Pairs disadvantaged young people with trained mentors for a year of regular support.",
        "goal": 15000.00,
        "raised": 6120.00,
    },
    {
        "id": "GENERAL",
        "name": "General Fund",
        "description": "Unrestricted -- goes wherever it's needed most across all our programmes.",
        "goal": None,
        "raised": 31870.00,
    },
]

CAMPAIGNS_BY_ID = {c["id"]: c for c in CAMPAIGNS}

# HMRC Gift Aid: a UK charity can claim an extra 25p per £1 donated by a UK
# taxpayer, at no extra cost to the donor. This is a real rate, not a demo
# simplification -- see the system prompt for how the agent should use it.
GIFT_AID_RATE = 0.25

# ---------------------------------------------------------------------------
# In-memory state -- reset any time by restarting the process. Swapped for
# real persistence and a real payment provider once this graduates out of
# prototype (same caveat as data.py's RESERVATIONS/ORDERS).
# ---------------------------------------------------------------------------

_donation_ids = itertools.count(1)

DONATIONS = []  # {id, amount, frequency, campaign_id, campaign_name, donor_name,
                 #  donor_email, anonymous, gift_aid, gift_aid_bonus,
                 #  dedication_type, dedication_name, message, status, payment}


def next_donation_id():
    return f"D{next(_donation_ids):04d}"
