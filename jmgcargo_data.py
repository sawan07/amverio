"""
Business data for the JMG Cargo quotation agent.

Unlike The Copper Fork / Bright Horizons Trust, JMG Cargo is a REAL business
(jmgcargo.com, JMG Cargo & Travel Ltd, company no. 05576500). Everything in
COMPANY / RATE_CARD / PROHIBITED_ITEMS below was taken from their public
website on 2026-10-13. Anything NOT published there is marked
"ASSUMPTION -- confirm with JMG" and is the first thing to check with them
before this goes in front of their customers.

The website only publishes "from" prices per kg and says prices can change
daily, so this agent gives an ESTIMATE ("from £X") and records a quote
request for the JMG team to confirm -- it never presents a firm price.
"""

import itertools

# ---------------------------------------------------------------------------
# Company identity -- from jmgcargo.com (home, contact, quote FAQ pages)
# ---------------------------------------------------------------------------

COMPANY = {
    "name": "JMG Cargo",
    "legal_name": "JMG Cargo & Travel Ltd",
    "tagline": "UK's Top Courier for Bangladesh & Asia",
    "address": "8 Fordham St, London E1 1HS (Whitechapel)",
    "phone": "020 7247 8878",
    "email": "info@jmgcargo.com",
    "opening_hours": "Monday to Saturday, 10am to 7pm",
    "website": "https://jmgcargo.com",
    "currency": "GBP",
    "services": [
        "Pick-up / collection service (book a collection and the team handles the rest)",
        "Drop-off at the main Whitechapel office or other locations (contact for list)",
        "Express delivery for urgent parcels",
        "Large items supported",
        "Insurance available for shipped items; secure packaging on request",
        "Door-to-door delivery to Dhaka, Chittagong, Sylhet and all major cities in Bangladesh",
        "Worldwide shipping (52 countries covered)",
    ],
    "payment_methods": "Cash, online bank transfer, and all major cards",
    "weight_limits": "Normally 1kg up to 100kg per shipment; larger/heavier items can be arranged",
    "discounts": "Special offers and discounts are available, especially for regular customers",
    "agents": "Branch offices and agents across the UK; you can also apply to become an agent",
    "stats": "Delivering since 2002; 2,000,000+ parcels delivered, 97.8% delivery success",
}

# ---------------------------------------------------------------------------
# Rate card -- "from" prices per kg, exactly as published on the Prices page.
# The site adds "Prices might change daily" to every one.
# ---------------------------------------------------------------------------

RATE_CARD = {
    "bangladesh": {"label": "Bangladesh", "from_per_kg": 6.00},
    "asia": {"label": "Asia", "from_per_kg": 6.00},
    "europe": {"label": "Europe", "from_per_kg": 3.50},
    "worldwide": {"label": "Worldwide", "from_per_kg": 6.00},
}

MIN_WEIGHT_KG = 1      # site: "From 1kg upto 100kg"
MAX_STANDARD_KG = 100  # above this -> "we can also arrange shipping for large items"

# ---------------------------------------------------------------------------
# ASSUMPTIONS -- not published by JMG. Industry-standard defaults so the
# estimate is sensible; confirm each one with JMG before going live.
# ---------------------------------------------------------------------------

# ASSUMPTION -- confirm with JMG: billable weight is rounded UP to the next
# whole kg (the site only ever quotes "per 1kg").
ROUND_UP_TO_KG = 1

# ASSUMPTION -- confirm with JMG: volumetric weight for bulky-but-light
# parcels = L x W x H (cm) / 5000, the usual air-courier divisor. Only used
# when the customer gives dimensions; the higher of actual vs volumetric is
# charged.
VOLUMETRIC_DIVISOR = 5000

# Collection, insurance and express are all offered, but JMG doesn't
# publish what they cost -- the agent says "the team will confirm" rather
# than inventing a number.

# ---------------------------------------------------------------------------
# Destination -> region. Bangladesh is its own headline market for JMG.
# Anything not listed falls back to "worldwide".
# ---------------------------------------------------------------------------

BANGLADESH_CITIES = [
    "dhaka", "chittagong", "chattogram", "sylhet", "khulna", "rajshahi",
    "barisal", "barishal", "rangpur", "mymensingh", "comilla", "cumilla",
    "narayanganj", "gazipur", "bogra", "bogura", "moulvibazar", "sunamganj",
    "habiganj", "cox's bazar", "jessore", "jashore", "feni", "noakhali",
]

ASIA_COUNTRIES = [
    "india", "pakistan", "sri lanka", "nepal", "bhutan", "maldives",
    "afghanistan", "china", "hong kong", "macau", "taiwan", "japan",
    "south korea", "korea", "mongolia", "thailand", "malaysia", "singapore",
    "indonesia", "philippines", "vietnam", "cambodia", "laos", "myanmar",
    "brunei", "uae", "united arab emirates", "dubai", "saudi arabia", "qatar",
    "kuwait", "bahrain", "oman", "jordan", "lebanon", "iraq", "kazakhstan",
    "uzbekistan",
]

EUROPE_COUNTRIES = [
    "ireland", "france", "germany", "italy", "spain", "portugal",
    "netherlands", "holland", "belgium", "luxembourg", "austria",
    "switzerland", "denmark", "sweden", "norway", "finland", "iceland",
    "poland", "czech republic", "czechia", "slovakia", "hungary", "romania",
    "bulgaria", "greece", "cyprus", "malta", "croatia", "slovenia", "serbia",
    "bosnia", "albania", "north macedonia", "montenegro", "estonia", "latvia",
    "lithuania", "ukraine", "moldova", "turkey",
]

# ---------------------------------------------------------------------------
# Prohibited items -- from the Illegal Items page. Each entry: what the
# customer sees, plus lowercase keywords used to spot it in a free-text
# contents description. Keyword matching is deliberately simple and errs
# towards flagging; the agent tells the customer to double-check with the
# team rather than treating a non-match as a guarantee.
# ---------------------------------------------------------------------------

PROHIBITED_ITEMS = [
    ("Aerosols / sprays / body sprays", ["aerosol", "spray", "deodorant", "body spray"]),
    ("Airbag modules", ["airbag"]),
    ("Animal skins, furs, any animal parts (including meat), ivory", ["animal skin", "fur", "ivory", "meat", "leather hide", "beef", "chicken", "mutton", "fish"]),
    ("Any item that is not boxed", ["unboxed", "not boxed", "loose"]),
    ("Valuables over £250 (art, antiques, precious stones) -- gold or silver over £50", ["gold", "silver", "jewellery", "jewelry", "diamond", "precious stone", "antique", "painting", "artwork"]),
    ("Boxes with a hazardous label (don't reuse old hazardous boxes)", ["hazardous label"]),
    ("Unnamed cheques or tickets", ["cheque", "ticket"]),
    ("Dangerous goods -- explosives, fireworks, Christmas crackers, radioactive material, weapons (incl. replica/deactivated), firearms, swords, knives, axes", ["explosive", "firework", "cracker", "radioactive", "weapon", "gun", "firearm", "rifle", "pistol", "ammunition", "sword", "knife", "knives", "axe", "dagger", "replica"]),
    ("Dry ice", ["dry ice"]),
    ("Engines, generators, gearboxes or parts that have contained oil/petrol (unless flushed)", ["engine", "generator", "gearbox", "petrol", "motor part"]),
    ("Fire extinguishers / life jackets", ["fire extinguisher", "extinguisher", "life jacket"]),
    ("Perishable food outside the EU", ["perishable", "fresh food", "fruit", "vegetable", "cooked food", "sweets", "mishti", "milk", "cheese", "food"]),
    ("Goods under ATA Carnet / temporary exports, FCR, FCT or CAD", ["carnet", "temporary export"]),
    ("Hazardous materials -- paint, adhesives, chemicals, flammable resins/solvents/liquids, compressed air, anything containing gas", ["paint", "adhesive", "glue", "chemical", "solvent", "flammable", "resin", "compressed", "gas", "lighter"]),
    ("Household goods with flammable/corrosive liquids -- oven/drain cleaner, perfume, aftershave, hairspray, nail varnish & remover, antiseptic wipes", ["oven cleaner", "drain cleaner", "perfume", "attar", "aftershave", "after shave", "hairspray", "hair spray", "nail varnish", "nail polish", "remover", "antiseptic", "bleach", "cologne"]),
    ("Human remains / body fluids", ["human remains", "ashes", "body fluid"]),
    ("Liquids, adhesives, paint, oil", ["liquid", "oil", "shampoo", "lotion", "ghee", "honey", "sauce", "drink", "juice"]),
    ("Live or dead animals", ["animal", "pet", "bird", "insect"]),
    ("Magnets or ferro-magnetic items", ["magnet", "speaker"]),
    ("Money, keys, negotiable items, payment cards", ["money", "cash", "currency", "banknote", "key", "credit card", "debit card", "bank card"]),
    ("Passports, birth certificates, driving licences", ["passport", "birth certificate", "driving licence", "driving license", "id card"]),
    ("Pornographic material", ["porn", "adult material"]),
    ("Medication (prescribed drugs)", ["medicine", "medication", "tablet", "pill", "drug", "prescription", "capsule", "syrup", "inhaler"]),
    ("Tobacco and tobacco products", ["tobacco", "cigarette", "cigar", "vape", "e-cigarette", "shisha"]),
    ("Wet or lithium batteries (dry cells are fine)", ["lithium", "battery", "batteries", "power bank", "powerbank"]),
]

RESTRICTED_NOTE = (
    "Restricted items can be sent but at the customer's own risk -- no "
    "compensation if lost or damaged, and enhanced cover doesn't apply. "
    "Prohibited items must never be sent: the shipment can be destroyed and "
    "the sender fined or prosecuted."
)

# ---------------------------------------------------------------------------
# In-memory quote requests -- reset on restart. Same demo caveat as the
# other verticals; in production these would go to JMG by email/CRM.
# ---------------------------------------------------------------------------

_quote_ids = itertools.count(1)

QUOTE_REQUESTS = []


def next_quote_id():
    return f"JMG-Q{next(_quote_ids):04d}"
