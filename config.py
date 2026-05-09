import os

# ================================================================
# FL PROPERTY INTEL — MASTER CONFIG
# One place to control everything. Do not duplicate settings
# elsewhere in the codebase.
# ================================================================

# ── Google Service Account ───────────────────────────────────────
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"

# ── Email Alerts ─────────────────────────────────────────────────
ALERT_EMAIL    = "info@rehabtampabay.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

# ── GoHighLevel ──────────────────────────────────────────────────
GHL_API_KEY  = os.environ.get("GHL_API_KEY", "")
GHL_BASE_URL = "https://rest.gohighlevel.com/v1"

# ── Sheet Tab Names (uniform across ALL county spreadsheets) ─────
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

# ── County Spreadsheets ──────────────────────────────────────────
COUNTIES = {
    "pinellas": {
        "name":        "Pinellas",
        "sheet_id":    "1fulzCWt9YM8IgniHyjHCmfglfkmW9lSVcKbnSrwh0pY",
        "public_base": "https://publicfiles.mypinellasclerk.gov/download",
        "active":      True,
    },
    "hillsborough": {
        "name":        "Hillsborough",
        "sheet_id":    "19XN6nWbxO7REtgneXE-ZIhdsa9H5GAmzG7SLubLJ4tY",
        "public_base": "https://publicfiles.hillsclerk.com/download",
        "active":      False,
    },
}

# ── Lead Scoring ─────────────────────────────────────────────────
SIGNAL_SCORES = {
    "lis_pendens":    40,
    "probate":        35,
    "tax_deeds":      35,
    "surplus_funds":  30,
    "mechanic_liens": 20,
    "judgments":      20,
    "evictions":      15,
}

SIGNAL_LABELS = {
    "lis_pendens":    "LIS PENDENS",
    "probate":        "PROBATE",
    "evictions":      "EVICTION",
    "mechanic_liens": "MECH LIEN",
    "judgments":      "JUDGMENT",
    "tax_deeds":      "TAX DEED",
    "surplus_funds":  "SURPLUS",
}

SIGNAL_COLORS = {
    "lis_pendens":    "#ef4444",
    "probate":        "#a78bfa",
    "evictions":      "#f59e0b",
    "mechanic_liens": "#f97316",
    "judgments":      "#14b8a6",
    "tax_deeds":      "#22c55e",
    "surplus_funds":  "#06b6d4",
}

HOT_LEAD_THRESHOLD = 60
