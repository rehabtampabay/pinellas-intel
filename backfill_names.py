"""
One-time backfill script.
Reads existing Mechanic Liens Raw and Judgments Raw tabs,
finds rows missing owner names, fetches p-files from Pinellas OR index,
and writes names back into the sheet.

Run once manually: python backfill_names.py
"""

import requests
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import sheets_helper

HEADERS  = {"User-Agent": "Mozilla/5.0 (compatible; PropertyIntel/1.0)"}
BASE     = config.COUNTIES["pinellas"]["public_base"]
SHEET_ID = config.COUNTIES["pinellas"]["sheet_id"]


def fetch_all_p_files(days_back=30):
    """
    Download p-files for the last N days and build a combined
    instrument -> party name lookup.
    """
    print("Fetching p-files (party index) for last " + str(days_back) + " days...")
    lookup = {}
    today  = datetime.today()
    found  = 0

    for i in range(days_back):
        date  = today - timedelta(days=i)
        fname = "p" + date.strftime("%Y%m%d") + "01id.52"
        url   = BASE + "/OFFICIAL_RECORDS/INDEXES_DAILY/" + fname
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if not r.ok or len(r.content) < 50:
                continue
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("latin-1")

            lines = [l for l in text.strip().splitlines() if "|" in l]
            if not lines:
                continue

            for line in lines:
                parts = line.split("|")
                if len(parts) < 6:
                    continue
                instrument = parts[2].strip()
                frm_to     = parts[4].strip().upper()
                party_name = parts[5].strip()
                if instrument and party_name:
                    if instrument not in lookup:
                        lookup[instrument] = []
                    if frm_to in ("FRM", "FROM", "GRANTOR", "DEBTOR"):
                        lookup[instrument].insert(0, party_name)
                    else:
                        lookup[instrument].append(party_name)

            found += 1
            print("  Loaded " + fname + " — " + str(len(lines)) + " lines")

        except Exception as e:
            print("  " + fname + ": " + str(e))

    print("Total p-files loaded: " + str(found) +
          " | Instruments indexed: " + str(len(lookup)))
    return lookup


def backfill_tab(tab_key, tab_name, lookup):
    """
    Reads a sheet tab, finds rows where 'Owner / Party' is empty,
    looks up the instrument number in the p-file lookup,
    and updates the cell with the found name.
    """
    print("\nBackfilling " + tab_name + "...")

    try:
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
        ws     = client.open_by_key(SHEET_ID).worksheet(tab_name)
    except Exception as e:
        print("  Could not open " + tab_name + ": " + str(e))
        return 0

    all_rows = ws.get_all_values()
    if len(all_rows) < 2:
        print("  Empty tab")
        return 0

    header = all_rows[0]
    print("  Columns: " + str(header))

    # Find column indices
    try:
        instr_col = next(i for i, h in enumerate(header)
                         if h.strip() in ("Instrument", "instrument"))
    except StopIteration:
        print("  No Instrument column found — skipping")
        return 0

    # Find or create "Owner / Party" column
    if "Owner / Party" in header:
        name_col = header.index("Owner / Party")
    else:
        # Add the column header
        name_col = len(header)
        ws.update_cell(1, name_col + 1, "Owner / Party")
        print("  Added 'Owner / Party' column at position " + str(name_col + 1))

    # Batch collect updates
    updates    = []
    found_ct   = 0
    missing_ct = 0

    for row_idx, row in enumerate(all_rows[1:], start=2):
        # Get existing name value
        existing_name = row[name_col].strip() if len(row) > name_col else ""
        if existing_name:
            continue  # Already has a name

        instrument = row[instr_col].strip() if len(row) > instr_col else ""
        if not instrument:
            continue

        names = lookup.get(instrument, [])
        if names:
            owner = names[0][:80]
            updates.append({
                "range": ws.cell(row_idx, name_col + 1).address,
                "values": [[owner]]
            })
            found_ct += 1
        else:
            missing_ct += 1

    # Apply updates in batches
    if updates:
        batch_size = 100
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i+batch_size]
            ws.batch_update(batch)
            print("  Updated rows " + str(i+1) + "–" + str(min(i+batch_size, len(updates))))
        print("  " + str(found_ct) + " names backfilled | " +
              str(missing_ct) + " instruments not in p-file index")
    else:
        print("  No rows needed backfilling")

    return found_ct


def main():
    print("=" * 50)
    print("PINELLAS NAME BACKFILL")
    print("=" * 50)

    # Load 30 days of p-files to cover existing records
    lookup = fetch_all_p_files(days_back=30)

    if not lookup:
        print("\nNo p-file data found. Cannot backfill.")
        return

    # Backfill mechanic liens
    backfill_tab("mechanic_liens", config.TABS["mechanic_liens"], lookup)

    # Backfill judgments
    backfill_tab("judgments", config.TABS["judgments"], lookup)

    print("\n" + "=" * 50)
    print("BACKFILL COMPLETE")
    print("=" * 50)


main()
