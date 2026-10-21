"""
Domain registry for the Amverio platform demo.

Each entry describes one agent persona/vertical available in this demo:
its tool schemas/functions, system prompt, and UI branding:

    get_domain("restaurant")    -- The Copper Fork: table booking + food ordering.

Adding an additional vertical later means adding one _load_* function and one
line in _LOADERS -- nothing else (app.py, chat.py, frontend) needs to change,
since they all go through get_domain()/list_domains().
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
        "brand_tag": "DINESYNC · AI ASSISTANT",
        "greeting": (
            "Hi, welcome to The Copper Fork. I'm DineSync, your AI restaurant assistant. "
            "I can book you a table or take a food order (pickup or delivery) — what would you like to do?"
        ),
        "new_conversation_label": "New order",
        "input_placeholder": "Book a table or place an order…",
        "system_prompt_base": system_prompt_base,
        "tool_schemas": TOOL_SCHEMAS,
        "tool_functions": TOOL_FUNCTIONS,
    }


_LOADERS = {
    "restaurant": _load_restaurant,
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
    out = []
    for domain_id in DOMAIN_IDS:
        cfg = get_domain(domain_id)
        entry = {field: cfg[field] for field in public_fields}
        # "path": a dedicated page (/<path>) that opens straight into this
        # agent. "listed": whether it shows as a card on the picker at /.
        entry["path"] = cfg.get("path")
        entry["listed"] = cfg.get("listed", True)
        entry["theme"] = cfg.get("theme")
        out.append(entry)
    return out


def domain_paths() -> dict:
    """{path: domain_id} for every domain that has its own dedicated page."""
    return {
        get_domain(d)["path"]: d
        for d in DOMAIN_IDS
        if get_domain(d).get("path")
    }
