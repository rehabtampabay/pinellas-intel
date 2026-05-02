"""
Pinellas County Unified Scraper — v2
Correct paths confirmed from live directory listing.

CIVIL/:
  - LIS_PENDENS_DAILY/         ✅ pre-foreclosure
  - WRIT_OF_POSSESSIONS_DAILY/ ✅ evictions
  - NEW_CASE_FILINGS_DAILY/    ✅ judgments + other civil

OFFICIAL_RECORDS/:
  - INDEXES_DAILY/             ✅ mechanic liens, HOA liens, judgments, deeds

PROBATE/:
  - NEW_ESTATE_CASE_FILINGS_DAILY/ ✅ probate
"""

import requests
import re
import csv
import io
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sheets_helper
import config

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PropertyIntel/1.0)"}

# Doc type codes in the Official Records index that signal motivated sellers
LIEN_CODES    = {"LNMECH", "LNHOA", "LNIRS", "LNCTY", "LNSTA", "LN"}
JUDGMENT_CODES = {"JUD", "CCJ", "DRJUD", "JUDL", "FJUD"}
DEED_CODES     = {"TDEED", "TAXDEED"}


# ─────────────────────────────────────────────────────────────
# HELPER: Fetch CSV from a directory listing page
# ─────────────────────────────────────────────────────────────

def fetch_csv_from_directory(directory_url, filename_pattern, days_back=10):
    """Finds and downloads matching CSVs from a Pinellas public files directory."""
    try:
        resp = requests.get(directory_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ Could not reach {directory_url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links = [a['href'] for a in soup.find_all('a', href=True)]

    today = datetime.today()
    # Build list of target date strings (e.g. "May 02, 2026")
    target_dates = [(today - timedelta(days=i)).strftime("%B %d, %Y") for i in range(days_back)]
    # Also try zero-padded variants (e.g. "May 2, 2026")
    target_dates += [(today - timedelta(days=i)).strftime("%B %-d, %Y") for i in range(days_back)]

    matched = []
    for link in links:
        fname = link.split("/")[-1].replace("%20", " ")
        for date_str in target_dates:
            if date_str in fname and re.search(filename_pattern, fname, re.IGNORECASE):
                full_url = directory_url.rstrip("/") + "/" + link.split("/")[-1]
                matched.append((date_str, full_url, fname))
                break

    if not matched:
        print(f"  ⚠️  No recent files matched in {directory_url}")
        return []

    all_rows = []
    for date_str, url, fname in sorted(set(matched), reverse=True)[:3]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if not r.ok or len(r.content) < 300:
                print(f"  ⚠️  {fname} too small or failed")
                continue
            # Try UTF-8, fall back to latin-1
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("latin-1")

            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
            if len(rows) > 1:
                print(f"  📥 {fname} → {len(rows)-1} records")
                if not all_rows:
                    all_rows.extend(rows)
                else:
                    all_rows.extend(rows[1:])  # skip header on subsequent files
        except Exception as e:
            print(f"  ❌ Error reading {fname}: {e}")

    return all_rows


def fetch_csv_by_date_format(base_url, fname_template, days_back=10):
    """For files named by date (MM-DD-YYYY format)."""
    today = datetime.today()
    all_rows = []
    for i in range(days_back):
        date = today - timedelta(days=i)
        fname = fname_template.format(date=date.strftime("%m-%d-%Y"))
        url = base_url.rstrip("/") + "/" + fname
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if not r.ok or len(r.content) < 300:
                continue
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("latin-1")
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
            if len(rows) > 1:
                print(f"  📥 {fname} → {len(rows)-1} records")
                all_rows.extend(rows)
                break
        except Exception as e:
            print(f"  ❌ {e}")
    return all_rows


# ─────────────────────────────────────────────────────────────
# SIGNAL 1: LIS PENDENS
# ─────────────────────────────────────────────────────────────

def scrape_lis_pendens():
    print("\n🔴 Lis Pendens (Pre-Foreclosure)...")
    url = "https://publicfiles.mypinellasclerk.gov/download/CIVIL/LIS_PENDENS_DAILY/"
    rows = fetch_csv_from_directory(url, r"Odyssey-JobOutput.*\.csv")
    if rows:
        return sheets_helper.append_rows_deduplicated(
            config.SHEETS["lis_pendens"], rows, case_col_index=3)
    print("  ❌ No data")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNAL 2: PROBATE / ESTATE
# ─────────────────────────────────────────────────────────────

def scrape_probate():
    print("\n🟣 Probate / Estate...")
    url = "https://publicfiles.mypinellasclerk.gov/download/PROBATE/NEW_ESTATE_CASE_FILINGS_DAILY/"

    # Try Odyssey-style filename first
    rows = fetch_csv_from_directory(url, r"Odyssey-JobOutput.*\.csv")

    # Fallback: date-named file
    if not rows:
        rows = fetch_csv_by_date_format(
            url, "EstateNewCaseFilingsDaily_{date}.csv")

    # Fallback 2: any CSV in that directory
    if not rows:
        rows = fetch_csv_from_directory(url, r"\.csv$")

    if rows:
        return sheets_helper.append_rows_deduplicated(
            config.SHEETS["probate"], rows, case_col_index=1)
    print("  ❌ No data")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNAL 3: EVICTIONS
# ─────────────────────────────────────────────────────────────

def scrape_evictions():
    print("\n🟡 Evictions (Writ of Possession)...")
    url = "https://publicfiles.mypinellasclerk.gov/download/CIVIL/WRIT_OF_POSSESSIONS_DAILY/"
    rows = fetch_csv_from_directory(url, r"Odyssey-JobOutput.*\.csv")
    if rows:
        return sheets_helper.append_rows_deduplicated(
            config.SHEETS["evictions"], rows, case_col_index=3)
    print("  ❌ No data")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNAL 4 + 5: MECHANIC LIENS + JUDGMENTS
# Source: OFFICIAL_RECORDS/INDEXES_DAILY/
# This single feed contains ALL recorded doc types — we filter by code
# ─────────────────────────────────────────────────────────────

def scrape_official_records_index():
    """
    Downloads the daily Official Records index and splits into:
    - Mechanic/HOA/IRS Liens
    - Judgments
    - Tax Deeds (bonus)
    Returns (lien_count, judgment_count, tax_deed_count)
    """
    print("\n📋 Official Records Index (Liens + Judgments + Tax Deeds)...")
    url = "https://publicfiles.mypinellasclerk.gov/download/OFFICIAL_RECORDS/INDEXES_DAILY/"
    rows = fetch_csv_from_directory(url, r"\.csv$", days_back=5)

    if not rows or len(rows) < 2:
        print("  ❌ No Official Records index data")
        return 0, 0, 0

    header = rows[0]
    print(f"  📊 Index columns: {header[:8]}")

    # Find the doc type column (usually named "DocType", "Document Type", "TYPE" etc.)
    doc_type_col = None
    for i, col in enumerate(header):
        if any(k in col.upper() for k in ["DOCTYPE", "DOC_TYPE", "DOCUMENT TYPE", "TYPE", "INSTRUMENT"]):
            doc_type_col = i
            break

    if doc_type_col is None:
        # If we can't find doc type column, push everything as general records
        print(f"  ⚠️  Can't find doc type column in: {header}")
        print(f"  ℹ️  Pushing all {len(rows)-1} records to Mechanic Liens tab as raw index")
        return sheets_helper.append_rows_deduplicated(
            config.SHEETS["mechanic_liens"], rows, case_col_index=1), 0, 0

    # Split rows by doc type
    lien_rows = [header]
    judgment_rows = [header]
    tax_deed_rows = [header]
    other_rows = [header]

    for row in rows[1:]:
        if len(row) <= doc_type_col:
            continue
        doc_type = row[doc_type_col].upper().strip()

        if any(code in doc_type for code in LIEN_CODES):
            lien_rows.append(row)
        elif any(code in doc_type for code in JUDGMENT_CODES):
            judgment_rows.append(row)
        elif any(code in doc_type for code in DEED_CODES):
            tax_deed_rows.append(row)
        else:
            other_rows.append(row)

    print(f"  🔧 Liens: {len(lien_rows)-1} | ⚖️  Judgments: {len(judgment_rows)-1} | 🏛️  Tax Deeds: {len(tax_deed_rows)-1}")

    lien_count = 0
    judgment_count = 0
    tax_deed_count = 0

    if len(lien_rows) > 1:
        lien_count = sheets_helper.append_rows_deduplicated(
            config.SHEETS["mechanic_liens"], lien_rows, case_col_index=1)

    if len(judgment_rows) > 1:
        judgment_count = sheets_helper.append_rows_deduplicated(
            config.SHEETS["judgments"], judgment_rows, case_col_index=1)

    if len(tax_deed_rows) > 1:
        tax_deed_count = sheets_helper.append_rows_deduplicated(
            config.SHEETS["tax_deeds"], tax_deed_rows, case_col_index=1)

    return lien_count, judgment_count, tax_deed_count


def scrape_mechanic_liens():
    """Wrapper — calls the shared official records scraper."""
    liens, _, _ = scrape_official_records_index()
    return liens


def scrape_judgments():
    """Judgments already handled in scrape_official_records_index."""
    return 0  # Already counted above


# ─────────────────────────────────────────────────────────────
# SIGNAL 6: TAX DEEDS + SURPLUS FUNDS
# Source: pinellas.realtdm.com
# ─────────────────────────────────────────────────────────────

def scrape_tax_deeds_and_surplus():
    print("\n🟢 Tax Deeds + Surplus Funds (realtdm)...")
    base = "https://pinellas.realtdm.com"
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        resp = session.get(f"{base}/public/cases/list", timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "table"})

        if table:
            rows_html = table.find_all("tr")
            data_rows = [["Status","Case Number","Date Created","Parcel Number",
                          "Sale Date","Opening Bid","Surplus Balance","County"]]
            surplus_rows = [["Status","Case Number","Date Created","Parcel Number",
                             "Sale Date","Surplus Balance","County"]]

            for tr in rows_html[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    cells.append("Pinellas")
                    data_rows.append(cells)
                    # Flag surplus if column 6 has a value > 0
                    if len(cells) > 6:
                        bal = str(cells[6]).replace("$","").replace(",","").strip()
                        try:
                            if float(bal) > 0:
                                surplus_rows.append(cells[:7])
                        except Exception:
                            pass

            td_added = sf_added = 0
            if len(data_rows) > 1:
                print(f"  📥 {len(data_rows)-1} tax deed records")
                td_added = sheets_helper.append_rows_deduplicated(
                    config.SHEETS["tax_deeds"], data_rows, case_col_index=2)
            if len(surplus_rows) > 1:
                print(f"  💰 {len(surplus_rows)-1} surplus fund records")
                sf_added = sheets_helper.append_rows_deduplicated(
                    config.SHEETS["surplus_funds"], surplus_rows, case_col_index=2)

            return td_added + sf_added

    except Exception as e:
        print(f"  ⚠️  realtdm failed: {e}")

    print("  ⚠️  Tax deed site may block scrapers — check manually at pinellas.realtdm.com")
    return 0


# ─────────────────────────────────────────────────────────────
# BONUS: NEW CASE FILINGS (Civil — catches judgments + more)
# ─────────────────────────────────────────────────────────────

def scrape_new_case_filings():
    """
    NEW_CASE_FILINGS_DAILY catches civil judgments, small claims,
    and other case types not in Lis Pendens or Evictions.
    """
    print("\n🔵 New Civil Case Filings...")
    url = "https://publicfiles.mypinellasclerk.gov/download/CIVIL/NEW_CASE_FILINGS_DAILY/"
    rows = fetch_csv_from_directory(url, r"Odyssey-JobOutput.*\.csv")
    if rows:
        return sheets_helper.append_rows_deduplicated(
            config.SHEETS["judgments"], rows, case_col_index=3)
    print("  ❌ No data")
    return 0
