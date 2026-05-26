"""
One-time cleanup script.
Clears Mechanic Liens Raw and Judgments Raw tabs,
then rewrites them with correct headers only.
The next daily scrape will repopulate with clean data.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

SHEET_ID = config.COUNTIES["pinellas"]["sheet_id"]

MECH_LIEN_HEADER = ["Instrument", "Owner / Party", "Doc Type", "Book", "Page", "Date Filed"]
JUDGMENT_HEADER  = ["Instrument", "Owner / Party", "Doc Type", "Book", "Page", "Date Filed"]

def clean_tab(client, sheet_id, tab_name, header):
    print(f"\nCleaning {tab_name}...")
    try:
        ws = client.open_by_key(sheet_id).worksheet(tab_name)
        all_rows = ws.get_all_values()
        print(f"  Found {len(all_rows)} rows (including any header)")

        # Clear everything
        ws.clear()
        print("  Cleared all rows")

        # Write clean header
        ws.append_row(header, value_input_option="USER_ENTERED")
        print(f"  Wrote header: {header}")

    except Exception as e:
        print(f"  ERROR on {tab_name}: {e}")


def main():
    from google.oauth2.service_account import Credentials
    import gspread

    creds = Credentials.from_service_account_file(
        config.GOOGLE_CREDENTIALS_FILE,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    client = gspread.authorize(creds)

    print("=" * 50)
    print("SHEET CLEANUP — MECH LIENS & JUDGMENTS")
    print("=" * 50)

    clean_tab(client, SHEET_ID, config.TABS["mechanic_liens"], MECH_LIEN_HEADER)
    clean_tab(client, SHEET_ID, config.TABS["judgments"],      JUDGMENT_HEADER)

    print("\n" + "=" * 50)
    print("DONE — Run daily scrape next to repopulate")
    print("=" * 50)

main()
