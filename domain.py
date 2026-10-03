"""
Domain registry for the Amverio demo.

Each entry describes one agent persona/vertical available in this demo:
its tool schemas/functions, system prompt, and UI branding. Unlike the
first version of this file, this does NOT pick a single "active" domain at
import time -- the web demo (app.py) now serves every registered domain at
once and lets the person using it choose who to talk to on a front screen,
with each conversation thread remembering which domain it started as.

The terminal harness (chat.py) has no picker screen, so it still picks ONE
domain to run as via the AMVERIO_DOMAIN environment variable, using
get_domain() below -- see chat.py.

    get_domain("restaurant")    -- The Copper Fork: table booking + food ordering.
    get_domain("fundraising")   -- Bright Horizons Trust: campaign donations.

Adding a third vertical later means adding one _load_* function and one
line in _LOADERS -- nothing else (app.py, chat.py, the frontend) needs to
change, since they all go through get_domain()/list_domains().
"""

import os


def _load_restaurant() -> dict:
    from tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "system_prompt.md")) as f:
        system_prompt_base = f.read()

    return {
        "id": "restaurant",
        "brand_name": "The Copper Fork",
        "brand_tag": "AMVERIO DEMO · TABLE BOOKING & ORDERING",
        "greeting": (
            "Hi, welcome to The Copper Fork. I can book you a table or take a "
            "food order (pickup or delivery) — what would you like to do?"
        ),
        "new_conversation_label": "New order",
        "input_placeholder": "Book a table or place an order…",
        "system_prompt_base": system_prompt_base,
        "tool_schemas": TOOL_SCHEMAS,
        "tool_functions": TOOL_FUNCTIONS,
    }


def _load_fundraising() -> dict:
    from fundraising_tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "fundraising_system_prompt.md")) as f:
        system_prompt_base = f.read()

    return {
        "id": "fundraising",
        "brand_name": "Bright Horizons Trust",
        "brand_tag": "AMVERIO DEMO · DONATIONS",
        "greeting": (
            "Hi, thanks for stopping by Bright Horizons Trust. I can tell you "
            "about our current campaigns or take a donation — what would you "
            "like to do?"
        ),
        "new_conversation_label": "New donation",
        "input_placeholder": "Make a donation or ask about our campaigns…",
        "system_prompt_base": system_prompt_base,
        "tool_schemas": TOOL_SCHEMAS,
        "tool_functions": TOOL_FUNCTIONS,
    }


# Order here is the order domains appear in the frontend picker.
_LOADERS = {
    "restaurant": _load_restaurant,
    "fundraising": _load_fundraising,
}

DOMAIN_IDS = list(_LOADERS.keys())

_cache: dict = {}


def get_domain(domain_id: str) -> dict:
    """
    Returns the full config dict for a domain id (case-insensitive),
    including its tool_functions -- only call this server-side. Raises
    KeyError for an unknown id; callers decide how to surface that (a loud
    startup failure in chat.py, an HTTP 400 in app.py).
    """
    key = (domain_id or "").strip().lower()
    if key not in _LOADERS:
        raise KeyError(domain_id)
    if key not in _cache:
        _cache[key] = _LOADERS[key]()
    return _cache[key]


def list_domains() -> list:
    """
    Public branding info for every registered domain, safe to hand to the
    frontend (no tool_functions/tool_schemas) -- used by the picker screen
    to render one card per available agent.
    """
    public_fields = (
        "id", "brand_name", "brand_tag", "greeting",
        "new_conversation_label", "input_placeholder",
    )
    return [
        {field: get_domain(domain_id)[field] for field in public_fields}
        for domain_id in DOMAIN_IDS
    ]
