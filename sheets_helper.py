import gspread
from google.oauth2.service_account import Credentials
import config

_client = None

def get_client():
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_CREDENTIALS_FILE,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        _client = gspread.authorize(creds)
    return _client

def get_sheet(tab_name):
    client = get_client()
    return client.open(config.SPREADSHEET_NAME).worksheet(tab_name)

def get_existing_case_numbers(tab_name, case_col_index=2):
    """Returns a set of case numbers already in a sheet tab to prevent duplicates."""
    try:
        sheet = get_sheet(tab_name)
        col_values = sheet.col_values(case_col_index)
        return set(col_values[1:])  # skip header
    except Exception as e:
        print(f"⚠️  Could not read existing case numbers: {e}")
        return set()

def append_rows_deduplicated(tab_name, rows, case_col_index=2):
    """
    Appends rows to sheet only if the case number isn't already present.
    Skips duplicate rows and header rows mixed into data.
    Returns count of new rows added.
    """
    if not rows:
        return 0

    sheet = get_sheet(tab_name)
    existing = get_existing_case_numbers(tab_name, case_col_index)

    header = rows[0]
    new_rows = []

    for row in rows[1:]:
        # Skip blank rows or rows that look like headers
        if not any(row):
            continue
        if row[0] == header[0]:  # Header repeated in data — skip
            continue

        # Deduplicate by case number
        if len(row) >= case_col_index:
            case_num = row[case_col_index - 1]
            if case_num and case_num in existing:
                continue
            existing.add(case_num)

        new_rows.append(row)

    if new_rows:
        sheet.append_rows(new_rows, value_input_option="USER_ENTERED")

    print(f"  ✅ {len(new_rows)} new rows → {tab_name}")
    return len(new_rows)

def ensure_header(tab_name, header_row):
    """Makes sure the first row of a sheet is the correct header."""
    sheet = get_sheet(tab_name)
    existing = sheet.row_values(1)
    if existing != header_row:
        sheet.insert_row(header_row, 1)
