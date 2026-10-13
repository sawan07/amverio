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
    get_domain("jmgcargo")      -- JMG Cargo: cargo/courier quotations. Real
                                   client, so it lives on its own URL
                                   (/jmgcargo) and is NOT shown on the
                                   shared demo picker -- see "path"/"listed".

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


def _load_jmgcargo() -> dict:
    from jmgcargo_tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "jmgcargo_system_prompt.md")) as f:
        system_prompt_base = f.read()

    return {
        "id": "jmgcargo",
        "brand_name": "JMG Cargo",
        "brand_tag": "INSTANT CARGO QUOTE",
        "greeting": (
            "Hi, welcome to JMG Cargo! I can give you a quick quote for "
            "sending parcels from the UK — where would you like to send them?"
        ),
        "new_conversation_label": "New quote",
        "input_placeholder": "e.g. 2 boxes, 30kg to Sylhet…",
        # Served on its own page at /jmgcargo and hidden from the shared
        # demo picker at /.
        "path": "jmgcargo",
        "listed": False,
        # JMG's own colours, taken from jmgcargo.com: navy top bar and
        # headings, red square-cornered call-to-action buttons, dark slate
        # text on white. Light only, like their site.
        "theme": {
            "color_scheme": "light",
            "logo_url": "/brands/jmgcargo/logo.jpg",
            "top_bar": "MON – SAT: 10am to 7pm  ·  CALL 020 7247 8878",
            "vars": {
                "--bg": "#f7f7f7",
                "--panel": "#ffffff",
                "--fg": "#28303d",
                "--muted": "#666666",
                "--line": "#dfe2e6",
                "--accent": "#ea1826",
                "--accent-fg": "#ffffff",
                "--bubble-user": "#04295d",
                "--bubble-user-fg": "#ffffff",
                "--bubble-agent": "#ffffff",
                "--bubble-agent-fg": "#28303d",
                "--brand-fg": "#04295d",
                "--topbar-bg": "#04295d",
                "--topbar-fg": "#ffffff",
                "--btn-radius": "3px",
                "--send-radius": "3px",
                "--tag-fg": "#ea1826",
                "--tag-font": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
                "--bubble-radius": "8px",
                "--font": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
            },
        },
        "system_prompt_base": system_prompt_base,
        "tool_schemas": TOOL_SCHEMAS,
        "tool_functions": TOOL_FUNCTIONS,
    }


# Order here is the order domains appear in the frontend picker.
_LOADERS = {
    "restaurant": _load_restaurant,
    "fundraising": _load_fundraising,
    "jmgcargo": _load_jmgcargo,
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
