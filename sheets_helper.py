# ================================================================
# SHEETS HELPER
# All Google Sheets operations go through here.
# Uses spreadsheet ID (not name) for reliability.
# ================================================================

import gspread
from google.oauth2.service_account import Credentials
import config

_clients = {}  # cache per credentials file

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client():
    if "main" not in _clients:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
        _clients["main"] = gspread.authorize(creds)
    return _clients["main"]


def open_sheet(sheet_id, tab_name):
    """Open a specific tab by spreadsheet ID and tab name."""
    client = get_client()
    return client.open_by_key(sheet_id).worksheet(tab_name)


def get_existing_values(sheet_id, tab_name, col_index=1):
    """Return a set of values from one column (for deduplication)."""
    try:
        ws = open_sheet(sheet_id, tab_name)
        vals = ws.col_values(col_index)
        return set(vals[1:])  # skip header
    except Exception as e:
        print("  Could not read existing values from " + tab_name + ": " + str(e))
        return set()


def append_new_rows(sheet_id, tab_name, rows, dedup_col=1):
    """
    Appends rows to a sheet tab, skipping duplicates.
    rows[0] must be the header row.
    dedup_col is 1-indexed column used for deduplication.
    Returns count of rows actually added.
    """
    if not rows or len(rows) < 2:
        return 0

    header   = rows[0]
    existing = get_existing_values(sheet_id, tab_name, dedup_col)
    new_rows = []

    for row in rows[1:]:
        if not any(str(c).strip() for c in row):
            continue  # skip blank rows
        if row[0] == header[0]:
            continue  # skip repeated header rows in data

        # Dedup check
        key = str(row[dedup_col - 1]).strip() if len(row) >= dedup_col else ""
        if key and key in existing:
            continue
        existing.add(key)
        new_rows.append(row)

    if new_rows:
        ws = open_sheet(sheet_id, tab_name)
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        print("  + " + str(len(new_rows)) + " rows → " + tab_name)

    return len(new_rows)


def read_all_rows(sheet_id, tab_name):
    """Read all rows from a tab. Returns [] if tab missing or empty."""
    try:
        ws   = open_sheet(sheet_id, tab_name)
        rows = ws.get_all_values()
        return rows if len(rows) >= 2 else []
    except Exception as e:
        print("  Skipping " + tab_name + ": " + str(e))
        return []
