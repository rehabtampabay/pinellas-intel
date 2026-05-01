import os

# === GOOGLE SHEETS ===
SPREADSHEET_NAME = "Courthouse Leads Master"
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"

# Sheet tab names
SHEETS = {
    "lis_pendens":     "Lis Pendens Raw",
    "probate":         "Probate Raw",
    "evictions":       "Evictions Pinellas Raw",
    "mechanic_liens":  "Mechanic Liens Raw",
    "judgments":       "Judgments Raw",
    "tax_deeds":       "Tax Deeds Raw",
    "surplus_funds":   "Surplus Funds Raw",
    "master":          "Master Dashboard",
}

# === GOHIGHLEVEL ===
GHL_API_KEY = os.environ.get("GHL_API_KEY", "")
GHL_BASE_URL = "https://rest.gohighlevel.com/v1"

# === EMAIL ALERTS ===
ALERT_EMAIL = "info@rehabtampabay.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

# === LEAD SCORING WEIGHTS ===
SIGNAL_SCORES = {
    "lis_pendens":    40,   # Pre-foreclosure — high motivation
    "probate":        35,   # Estate sale — often must sell
    "tax_deeds":      35,   # Delinquent taxes — often must sell
    "mechanic_liens": 20,   # Cash-flow problem
    "judgments":      20,   # Legal pressure
    "evictions":      15,   # Landlord stress signal
    "surplus_funds":  30,   # Owes them money — highly motivated contact
}

# Score threshold for "hot lead"
HOT_LEAD_THRESHOLD = 60

# === PINELLAS PUBLIC FILES BASE ===
PINELLAS_PUBLIC_BASE = "https://publicfiles.mypinellasclerk.gov/download"
