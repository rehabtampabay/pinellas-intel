#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# run_hillsborough_local.py
#
# Runs on YOUR MAC (not GitHub Actions) to scrape Hillsborough County data.
# publicrec.hillsclerk.com blocks GitHub's datacenter IPs but allows
# residential IPs like your home internet connection.
#
# SETUP (one time):
#   1. Copy this file and google_credentials.json to ~/fl-intel/
#   2. pip3 install requests gspread google-auth
#   3. Schedule with launchd (instructions below)
#
# SCHEDULE WITH LAUNCHD:
#   Copy com.rehabtampabay.hillsborough.plist to ~/Library/LaunchAgents/
#   Then run: launchctl load ~/Library/LaunchAgents/com.rehabtampabay.hillsborough.plist
#   It will run Mon-Fri at 2:05pm (just after the GitHub workflow)
#
# MANUAL RUN:
#   cd ~/fl-intel && python3 run_hillsborough_local.py
# ─────────────────────────────────────────────────────────────────────────────

import sys
import os

# ── Point to your credentials and config ──────────────────────────────────────
# Edit this path if you put files somewhere else
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

os.environ.setdefault("GOOGLE_CREDENTIALS_FILE",
                      os.path.join(SCRIPT_DIR, "google_credentials.json"))

# ── Now import the scraper ────────────────────────────────────────────────────
# This imports config and sheets_helper from the same directory
import config
import sheets_helper

# Patch config to point credentials to local file
config.GOOGLE_CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "google_credentials.json")

from scrapers.hillsborough import scrape_hillsborough

from datetime import datetime

def main():
    start = datetime.now()
    print("=" * 50)
    print(f"HILLSBOROUGH SCRAPE — {start.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    results = scrape_hillsborough()

    elapsed   = (datetime.now() - start).seconds
    total_new = sum(results.values())

    print("=" * 50)
    print(f"DONE — {total_new} new records | {elapsed}s")
    for sig, count in results.items():
        if count:
            print(f"  {config.SIGNAL_LABELS.get(sig, sig)}: {count}")
    print("=" * 50)
    print()
    print("Data written to Hillsborough Google Sheet.")
    print("The GitHub workflow will include it in tonight's dashboard update.")

if __name__ == "__main__":
    main()
