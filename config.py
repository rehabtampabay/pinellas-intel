# ─────────────────────────────────────────────────────────────────────────────
# config.py  —  FL Property Intel
# Central configuration for all counties, signals, and scoring.
# ─────────────────────────────────────────────────────────────────────────────

import os

# ── Google credentials ────────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"

# ── Email ─────────────────────────────────────────────────────────────────────
ALERT_EMAIL    = "info@rehabtampabay.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

# ── Scoring thresholds ────────────────────────────────────────────────────────
HOT_LEAD_THRESHOLD = 60
WARM_THRESHOLD     = 40

# ── Signal base scores ────────────────────────────────────────────────────────
# Calibrated so that:
#   - Recent (<=30 days) probate / lis pendens = HOT
#   - Old (>90 days) records score WARM at best (no recency bonus)
#   - Evictions / mechanic liens only hit HOT with strong recency
SIGNAL_SCORES = {
    "lis_pendens":    40,
    "probate":        45,
    "evictions":      25,
    "mechanic_liens": 20,
    "judgments":      25,
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
COUNTIES = {
    "pinellas": {
        "active":      True,
        "name":        "Pinellas",
        "sheet_id":    "1fulzCWt9YM8IgniHyjHCmfglfkmW9lSVcKbnSrwh0pY",
        "public_base": "https://publicfiles.mypinellasclerk.gov/download",
    },
    "hillsborough": {
        "active":   True,
        "name":     "Hillsborough",
        "sheet_id": "19XN6nWbxO7REtgneXE-ZIhdsa9H5GAmzG7SLubLJ4tY",
    },
    "pasco": {
        "active":   False,
        "name":     "Pasco",
        "sheet_id": "",
    },
}
