import gspread
from google.oauth2.service_account import Credentials
import config

_clients = {}

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
    client = get_client()
    return client.open_by_key(sheet_id).worksheet(tab_name)


def get_existing_values(sheet_id, tab_name, col_index=1, col_index2=None):
    """
    Returns a set of values for deduplication.
    If col_index2 provided, combines two columns as 'val1|val2'.
    This handles probate where same case number gets new filings.
    """
    try:
        ws   = open_sheet(sheet_id, tab_name)
        col1 = ws.col_values(col_index)
        if col_index2:
            col2 = ws.col_values(col_index2)
            combined = set()
            for i in range(1, max(len(col1), len(col2))):
                v1 = col1[i] if i < len(col1) else ""
                v2 = col2[i] if i < len(col2) else ""
                if v1 or v2:
                    combined.add(v1 + "|" + v2)
            return combined
        return set(col1[1:])
    except Exception as e:
        print("  Could not read existing values from " + tab_name + ": " + str(e))
        return set()


def append_new_rows(sheet_id, tab_name, rows, dedup_col=1, dedup_col2=None):
    """
    Appends rows to a sheet tab, skipping duplicates.
    rows[0] must be the header row.
    dedup_col is 1-indexed.
    dedup_col2 (optional) creates a compound key for better dedup.
    Returns count of rows actually added.
    """
    if not rows or len(rows) < 2:
        return 0

    header   = rows[0]
    existing = get_existing_values(sheet_id, tab_name, dedup_col, dedup_col2)
    new_rows = []

    for row in rows[1:]:
        if not any(str(c).strip() for c in row):
            continue
        if row[0] == header[0]:
            continue

        # Build dedup key
        v1 = str(row[dedup_col - 1]).strip() if len(row) >= dedup_col else ""
        if dedup_col2:
            v2  = str(row[dedup_col2 - 1]).strip() if len(row) >= dedup_col2 else ""
            key = v1 + "|" + v2
        else:
            key = v1

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
    """Read all rows. Returns [] if tab missing or empty."""
    try:
        ws   = open_sheet(sheet_id, tab_name)
        rows = ws.get_all_values()
        return rows if len(rows) >= 2 else []
    except Exception as e:
        print("  Skipping " + tab_name + ": " + str(e))
        return []
