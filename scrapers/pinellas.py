# ================================================================
# PINELLAS COUNTY SCRAPER v4
# Fixed based on actual log output analysis:
# - Probate: use date-format filename (EstateNewCaseFilingsDaily_MM-DD-YYYY.csv)
# - Liens/Judgments: l-file format is instrument-based, not doc-type codes
# - Tax Deeds: realtdm blocks scrapers, use NEW_CASE_FILINGS_DAILY instead
# - Surplus Funds: use REGISTRY_TRUST_BALANCES_DAILY (court registry money)
# ================================================================

import requests
import csv
import io
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import sheets_helper

HEADERS  = {"User-Agent": "Mozilla/5.0 (compatible; PropertyIntel/1.0)"}
BASE     = config.COUNTIES["pinellas"]["public_base"]
SHEET_ID = config.COUNTIES["pinellas"]["sheet_id"]


# ── HELPER: Odyssey CSV directories (LIS PENDENS, EVICTIONS) ────

def fetch_odyssey_csv(directory_url, days_back=7):
    """
    Downloads CSVs from Pinellas public files directory.
    Files named like: Odyssey-JobOutput-May 14, 2026 03-59-52-13754140-2.csv
    Starts from today (i=0) since we run at 2pm and files post at 9am.
    """
    try:
        resp = requests.get(directory_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print("  Could not reach " + directory_url + ": " + str(e))
        return []

    soup  = BeautifulSoup(resp.text, "html.parser")
    links = [a["href"] for a in soup.find_all("a", href=True)]

    today   = datetime.today()
    targets = []
    for i in range(days_back):
        d = today - timedelta(days=i)
        targets.append(d.strftime("%B %d, %Y"))
        try:
            targets.append(d.strftime("%B %-d, %Y"))
        except Exception:
            pass

    matched = []
    for link in links:
        fname = link.split("/")[-1].replace("%20", " ")
        if not fname.lower().endswith(".csv"):
            continue
        for t in targets:
            if t in fname:
                full_url = directory_url.rstrip("/") + "/" + link.split("/")[-1]
                matched.append((t, full_url, fname))
                break

    if not matched:
        print("  No recent CSV files found")
        return []

    all_rows = []
    for _, url, fname in sorted(set(matched), reverse=True)[:3]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if not r.ok or len(r.content) < 300:
                continue
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("latin-1")
            reader = csv.reader(io.StringIO(text))
            rows   = list(reader)
            if len(rows) > 1:
                print("  Downloaded " + fname + " — " + str(len(rows)-1) + " records")
                if not all_rows:
                    all_rows.extend(rows)
                else:
                    all_rows.extend(rows[1:])
        except Exception as e:
            print("  Error: " + str(e))

    return all_rows


# ── HELPER: Date-format CSV (PROBATE) ───────────────────────────

def fetch_date_format_csv(base_url, template, days_back=7, min_size=500):
    """
    For files named EstateNewCaseFilingsDaily_MM-DD-YYYY.csv
    Tries today first then works backwards.
    """
    today = datetime.today()
    for i in range(days_back):
        date  = today - timedelta(days=i)
        fname = template.format(date=date.strftime("%m-%d-%Y"))
        url   = base_url.rstrip("/") + "/" + fname
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if not r.ok or len(r.content) < min_size:
                continue
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("latin-1")
            reader = csv.reader(io.StringIO(text))
            rows   = list(reader)
            if len(rows) > 1:
                print("  Downloaded " + fname + " — " + str(len(rows)-1) + " records")
                return rows
        except Exception as e:
            print("  " + fname + ": " + str(e))
    return []


# ── SIGNAL 1: LIS PENDENS ────────────────────────────────────────

def scrape_lis_pendens():
    print("\nLIS PENDENS...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/LIS_PENDENS_DAILY/")
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["lis_pendens"], rows, dedup_col=3)
    return 0


# ── SIGNAL 2: PROBATE ────────────────────────────────────────────

def scrape_probate():
    print("\nPROBATE...")
    # Files: EstateNewCaseFilingsDaily_05-14-2026.csv
    # Min size 500 to skip empty 468-byte files
    rows = fetch_date_format_csv(
        BASE + "/PROBATE/NEW_ESTATE_CASE_FILINGS_DAILY/",
        "EstateNewCaseFilingsDaily_{date}.csv",
        days_back=7,
        min_size=500
    )
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["probate"], rows, dedup_col=1)
    print("  No probate data found")
    return 0


# ── SIGNAL 3: EVICTIONS ──────────────────────────────────────────

def scrape_evictions():
    print("\nEVICTIONS...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/WRIT_OF_POSSESSIONS_DAILY/")
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["evictions"], rows, dedup_col=3)
    return 0


# ── SIGNAL 4: MECHANIC LIENS + JUDGMENTS ─────────────────────────
# Source: OFFICIAL_RECORDS/INDEXES_DAILY/l-file
# Real format discovered from logs:
# The "doc types" showing as numbers means col[0] is NOT doc type.
# Need to fetch and inspect actual raw content first line.

def scrape_official_records_index():
    print("\nOFFICIAL RECORDS INDEX...")

    lien_count = judgment_count = tax_deed_count = 0

    today = datetime.today()
    for i in range(5):
        date  = today - timedelta(days=i)
        fname = "l" + date.strftime("%Y%m%d") + "01id.52"
        url   = BASE + "/OFFICIAL_RECORDS/INDEXES_DAILY/" + fname
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if not r.ok or len(r.content) < 50:
                continue
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("latin-1")

            lines = text.strip().splitlines()
            if not lines:
                continue

            # Print first 3 lines so we can see actual format
            print("  l-file sample (first 3 lines):")
            for ln in lines[:3]:
                print("    " + ln[:120])

            # Parse based on actual pipe format
            # From sample data: DPA|52||1|FRM|NAME
            # Fields: DocType|CountyCode|InstrumentNum|SeqNum|FRM_TO|PartyName
            lien_rows = [["Doc Type", "Instrument", "Party Name", "FRM/TO", "Date Filed"]]
            jud_rows  = [["Doc Type", "Instrument", "Party Name", "FRM/TO", "Date Filed"]]
            filed_date = date.strftime("%m/%d/%Y")

            seen = set()
            for line in lines:
                parts = line.split("|")
                if len(parts) < 4:
                    continue

                doc_type   = parts[0].strip().upper()
                instrument = parts[2].strip()
                frm_to     = parts[4].strip() if len(parts) > 4 else ""
                party_name = parts[5].strip() if len(parts) > 5 else ""

                # Skip if instrument already seen
                if instrument and instrument in seen:
                    continue
                if instrument:
                    seen.add(instrument)

                # Lien types
                if any(x in doc_type for x in ["LNMECH","LNHOA","LNIRS","LNCTY","LNCON","LNSTA","LN"]):
                    lien_rows.append([doc_type, instrument, party_name, frm_to, filed_date])
                # Judgment types
                elif any(x in doc_type for x in ["JUD","CCJ","DRJUD","FJUD","JUDO"]):
                    jud_rows.append([doc_type, instrument, party_name, frm_to, filed_date])

            # Log all unique doc types found for debugging
            all_types = list(set(line.split("|")[0].strip() for line in lines if "|" in line))
            print("  Unique doc types in l-file: " + str(sorted(all_types)[:30]))
            print("  Liens found: " + str(len(lien_rows)-1))
            print("  Judgments found: " + str(len(jud_rows)-1))

            if len(lien_rows) > 1:
                lien_count = sheets_helper.append_new_rows(
                    SHEET_ID, config.TABS["mechanic_liens"], lien_rows, dedup_col=2)

            if len(jud_rows) > 1:
                judgment_count = sheets_helper.append_new_rows(
                    SHEET_ID, config.TABS["judgments"], jud_rows, dedup_col=2)

            break  # Got a file, stop

        except Exception as e:
            print("  l-file error: " + str(e))

    # d-file for tax deeds
    print("  Fetching d-file for tax deeds...")
    for i in range(5):
        date  = today - timedelta(days=i)
        fname = "d" + date.strftime("%Y%m%d") + "01id.52"
        url   = BASE + "/OFFICIAL_RECORDS/INDEXES_DAILY/" + fname
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if not r.ok or len(r.content) < 50:
                continue
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("latin-1")

            lines = lines = text.strip().splitlines()
            print("  d-file sample (first 3 lines):")
            for ln in lines[:3]:
                print("    " + ln[:120])

            all_types = list(set(line.split("|")[0].strip() for line in lines if "|" in line))
            print("  Unique doc types in d-file: " + str(sorted(all_types)[:30]))

            deed_rows = [["Doc Type", "Instrument", "Party Name", "FRM/TO", "Date Filed"]]
            seen = set()
            filed_date = date.strftime("%m/%d/%Y")

            for line in lines:
                parts = line.split("|")
                if len(parts) < 4:
                    continue
                doc_type   = parts[0].strip().upper()
                instrument = parts[2].strip()
                frm_to     = parts[4].strip() if len(parts) > 4 else ""
                party_name = parts[5].strip() if len(parts) > 5 else ""

                if instrument and instrument in seen:
                    continue
                if instrument:
                    seen.add(instrument)

                if any(x in doc_type for x in ["TDEED","TAXDEED","CTD","SRTD","TAX"]):
                    deed_rows.append([doc_type, instrument, party_name, frm_to, filed_date])

            if len(deed_rows) > 1:
                tax_deed_count = sheets_helper.append_new_rows(
                    SHEET_ID, config.TABS["tax_deeds"], deed_rows, dedup_col=2)

            break
        except Exception as e:
            print("  d-file error: " + str(e))

    return lien_count, judgment_count, tax_deed_count


# ── SIGNAL 5: NEW CASE FILINGS (catches judgments + tax deed apps)

def scrape_new_case_filings():
    """
    NEW_CASE_FILINGS_DAILY catches civil judgments, small claims,
    tax deed applications and other case types.
    Filter for judgment and tax deed case types.
    """
    print("\nNEW CASE FILINGS (judgments + tax deed apps)...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/NEW_CASE_FILINGS_DAILY/")
    if not rows or len(rows) < 2:
        print("  No data")
        return 0, 0

    header = rows[0]
    print("  Columns: " + str(header[:8]))

    # Find case type column
    ct_col = None
    for i, h in enumerate(header):
        if "CASE TYPE" in h.upper() or "CASETYPE" in h.upper():
            ct_col = i
            break

    if ct_col is None:
        print("  Could not find Case Type column")
        return 0, 0

    jud_rows  = [header]
    tax_rows  = [header]

    for row in rows[1:]:
        if len(row) <= ct_col:
            continue
        ct = row[ct_col].upper()
        if any(x in ct for x in ["JUDGMENT","GARNISH","SMALL CLAIM"]):
            jud_rows.append(row)
        elif any(x in ct for x in ["TAX DEED","TAXDEED","TAX CERT"]):
            tax_rows.append(row)

    print("  Judgment cases: " + str(len(jud_rows)-1))
    print("  Tax deed cases: " + str(len(tax_rows)-1))

    jud_added = tax_added = 0
    if len(jud_rows) > 1:
        jud_added = sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["judgments"], jud_rows, dedup_col=3)
    if len(tax_rows) > 1:
        tax_added = sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["tax_deeds"], tax_rows, dedup_col=3)

    return jud_added, tax_added


# ── SIGNAL 6: SURPLUS FUNDS ──────────────────────────────────────
# Source: CIVIL/REGISTRY_TRUST_BALANCES_DAILY/
# This is money held in court registry from foreclosure auction
# surplus — former owners are owed this money

def scrape_surplus_funds():
    print("\nSURPLUS FUNDS (Registry Trust Balances)...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/REGISTRY_TRUST_BALANCES_DAILY/")
    if not rows or len(rows) < 2:
        print("  No surplus data found")
        return 0

    print("  Columns: " + str(rows[0][:8]))
    return sheets_helper.append_new_rows(
        SHEET_ID, config.TABS["surplus_funds"], rows, dedup_col=3)


# ── LEGACY: Tax deeds via realtdm (kept as fallback) ─────────────

def scrape_tax_deeds_and_surplus():
    """realtdm.com blocks scrapers — returns 0, use new approach above."""
    print("\nTAX DEEDS (realtdm — blocked, skipping)...")
    return 0
