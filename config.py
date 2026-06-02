# ─────────────────────────────────────────────────────────────────────────────
# config.py  —  FL Property Intel
# Central configuration for all counties, signals, and scoring.
# ─────────────────────────────────────────────────────────────────────────────

import os

# ── Email ─────────────────────────────────────────────────────────────────────
ALERT_EMAIL    = "info@rehabtampabay.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

# ── Scoring thresholds ────────────────────────────────────────────────────────
HOT_LEAD_THRESHOLD = 60   # score >= 60 → hot
WARM_THRESHOLD     = 40   # score >= 40 → warm

# ── Signal base scores ────────────────────────────────────────────────────────
SIGNAL_SCORES = {
    "lis_pendens":    35,
    "probate":        30,
    "evictions":      25,
    "mechanic_liens": 20,
    "judgments":      20,
    "tax_deeds":      40,
    "surplus_funds":  30,
}

# ── Signal display labels ─────────────────────────────────────────────────────
SIGNAL_LABELS = {
    "lis_pendens":    "LIS PENDENS",
    "probate":        "PROBATE",
    "evictions":      "EVICTION",
    "mechanic_liens": "MECH LIEN",
    "judgments":      "JUDGMENT",
    "tax_deeds":      "TAX DEED",
    "surplus_funds":  "SURPLUS",
}

# ── Signal dashboard colors ───────────────────────────────────────────────────
SIGNAL_COLORS = {
    "lis_pendens":    "#ef4444",
    "probate":        "#a78bfa",
    "evictions":      "#f59e0b",
    "mechanic_liens": "#f97316",
    "judgments":      "#14b8a6",
    "tax_deeds":      "#22c55e",
    "surplus_funds":  "#3b82f6",
}

# ── Sheet tab names (same for all counties) ───────────────────────────────────
# Each county's Google Sheet uses identical tab names.
TABS = {
    "lis_pendens":    "Lis Pendens Raw",
    "probate":        "Probate Raw",
    "evictions":      "Evictions Raw",
    "mechanic_liens": "Mechanic Liens Raw",
    "judgments":      "Judgments Raw",
    "tax_deeds":      "Tax Deeds Raw",
    "surplus_funds":  "Surplus Funds Raw",
    "dashboard":      "Master Dashboard",
}

# ── Counties ──────────────────────────────────────────────────────────────────
# To add a new county:
#   1. Create a Google Sheet with the tab names above
#   2. Add an entry here with active=True and the sheet_id
#   3. Add the corresponding scraper in run_all.py
COUNTIES = {
    "pinellas": {
        "active":   True,
        "name":     "Pinellas",
        "sheet_id": "1fulzCWt9YM8IgniHyjHCmfglfkmW9lSVcKbnSrwh0pY",
    },
    "hillsborough": {
        "active":   True,
        "name":     "Hillsborough",
        "sheet_id": "19XN6nWbxO7REtgneXE-ZIhdsa9H5GAmzG7SLubLJ4tY",
    },
    "pasco": {
        "active":   False,
        "name":     "Pasco",
        "sheet_id": "",   # fill in when ready
    },
}
