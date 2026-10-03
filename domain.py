"""
Domain switch for the Amverio demo.

Same app (app.py for the web demo, chat.py for the terminal harness), same
deployment, same env-var-driven config pattern as OPENAI_API_KEY -- only
AMVERIO_DOMAIN changes which agent persona/toolset actually runs. This lets
one Coolify app serve either vertical depending on what's being demoed,
without maintaining two codebases.

    AMVERIO_DOMAIN=restaurant   (default) -- The Copper Fork: table booking + food ordering.
    AMVERIO_DOMAIN=fundraising            -- Bright Horizons Trust: campaign donations.

Locally:   export AMVERIO_DOMAIN=fundraising
Coolify:   Application -> Environment Variables -> add AMVERIO_DOMAIN,
           same place OPENAI_API_KEY lives -- then redeploy (env var changes
           need a redeploy to take effect, a restart alone won't pick it up).

app.py and chat.py import everything they need from here instead of
reaching into tools.py / fundraising_tools.py / *_system_prompt.md directly,
so neither of them needs to know which domain is active.
"""

import os

DOMAIN = os.environ.get("AMVERIO_DOMAIN", "restaurant").strip().lower()

_here = os.path.dirname(os.path.abspath(__file__))

if DOMAIN == "restaurant":
    from tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

    with open(os.path.join(_here, "system_prompt.md")) as _f:
        SYSTEM_PROMPT_BASE = _f.read()

    BRAND_NAME = "The Copper Fork"
    BRAND_TAG = "AMVERIO DEMO · TABLE BOOKING & ORDERING"
    GREETING = (
        "Hi, welcome to The Copper Fork. I can book you a table or take a "
        "food order (pickup or delivery) — what would you like to do?"
    )
    NEW_CONVERSATION_LABEL = "New order"
    INPUT_PLACEHOLDER = "Book a table or place an order…"

elif DOMAIN == "fundraising":
    from fundraising_tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

    with open(os.path.join(_here, "fundraising_system_prompt.md")) as _f:
        SYSTEM_PROMPT_BASE = _f.read()

    BRAND_NAME = "Bright Horizons Trust"
    BRAND_TAG = "AMVERIO DEMO · DONATIONS"
    GREETING = (
        "Hi, thanks for stopping by Bright Horizons Trust. I can tell you "
        "about our current campaigns or take a donation — what would you "
        "like to do?"
    )
    NEW_CONVERSATION_LABEL = "New donation"
    INPUT_PLACEHOLDER = "Make a donation or ask about our campaigns…"

else:
    raise RuntimeError(
        f"Unknown AMVERIO_DOMAIN={DOMAIN!r}. Expected 'restaurant' or 'fundraising'."
    )
