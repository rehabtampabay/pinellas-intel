"""
One-time cleanup: removes d-file probate recordings from Probate Raw.
These are rows where Case Number looks like an instrument number (all digits)
rather than a real case number like 26-005201-ES.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from google.oauth2.service_account import Credentials
import gspread

SHEET_ID = config.COUNTIES["pinellas"]["sheet_id"]
TAB      = config.TABS["probate"]

def main():
    creds = Credentials.from_service_account_file(
        config.GOOGLE_CREDENTIALS_FILE,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    client = gspread.authorize(creds)
    ws     = client.open_by_key(SHEET_ID).worksheet(TAB)

    print("Reading Probate Raw...")
    rows = ws.get_all_values()
    print(f"  Total rows: {len(rows)}")

    # Find rows to delete — instrument numbers are all digits, 10+ chars
    # Real case numbers look like: 26-005201-ES
    rows_to_delete = []
    for i, row in enumerate(rows[1:], start=2):  # skip header
        case_num = row[2].strip() if len(row) > 2 else ""
        # Junk rows: case number is all digits (instrument number)
        if case_num.isdigit() and len(case_num) >= 8:
            rows_to_delete.append(i)

    print(f"  Junk rows to delete: {len(rows_to_delete)}")

    # Delete in reverse order so row numbers don't shift
    for row_idx in reversed(rows_to_delete):
        ws.delete_rows(row_idx)

    print(f"  Done — deleted {len(rows_to_delete)} junk rows")

main()
