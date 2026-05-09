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

BASE = "https://publicfiles.mypinellasclerk.gov/download"

# Doc type codes that signal motivated sellers
LIEN_CODES     = {"LNMECH", "LNHOA", "LNIRS", "LNCTY", "LNSTA", "LNCON"}
JUDGMENT_CODES = {"JUD", "CCJ", "DRJUD", "JUDL", "FJUD", "JUDO"}
DEED_CODES     = {"TDEED", "TAXDEED", "CTD", "SRTD"}


# ─────────────────────────────────────────────────────────────
# HELPER: Build today's Official Records filename
# Format: {prefix}2026{MMDD}01id.52
# prefix: d=deeds, l=liens, m=mortgages, p=parties
# ─────────────────────────────────────────────────────────────

def build_or_filename(prefix, date):
    return f"{prefix}{date.strftime('%Y%m%d')}01id.52"


def fetch_or_file(prefix, days_back=5):
    """
    Downloads the pipe-delimited Official Records index file.
    Returns list of parsed rows as dicts.
    """
    today = datetime.today()
    for i in range(1, days_back + 1):
        date = today - timedelta(days=i)
        fname = build_or_filename(prefix, date)
        url = f"{BASE}/OFFICIAL_RECORDS/INDEXES_DAILY/{fname}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if not r.ok or len(r.content) < 50:
                continue
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("latin-1")

            rows = []
            for line in text.strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 5:
                    rows.append({
                        "doc_type":   parts[0].strip(),
                        "county":     parts[1].strip(),
                        "instrument": parts[2].strip(),
                        "seq":        parts[3].strip(),
                        "frm_to":     parts[4].strip(),
                        "name":       parts[5].strip() if len(parts) > 5 else "",
                        "date_filed": date.strftime("%Y-%m-%d"),
                        "source_file": fname,
                    })

            if rows:
                print(f"  📥 {fname} → {len(rows)} raw lines")
                return rows, date.strftime("%Y-%m-%d")

        except Exception as e:
            print(f"  ⚠️  {fname}: {e}")

    return [], None


def rows_to_sheet_format(records, sheet_cols):
    """Converts list of dicts to [header, row, row...] format for Sheets."""
    if not records:
        return []
    result = [sheet_cols]
    for r in records:
        result.append([r.get(c, "") for c in sheet_cols])
    return result


# ─────────────────────────────────────────────────────────────
# HELPER: Odyssey CSV files (Lis Pendens, Evictions)
# ─────────────────────────────────────────────────────────────

def fetch_odyssey_csv(directory_url, days_back=10):
    try:
        resp = requests.get(directory_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ {directory_url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links = [a['href'] for a in soup.find_all('a', href=True)]

    today = datetime.today()
    targets = []
    for i in range(1, days_back + 1):
        d = today - timedelta(days=i)
        targets.append(d.strftime("%B %d, %Y"))
        targets.append(d.strftime("%B %-d, %Y"))

    matched = []
    for link in links:
        fname = link.split("/")[-1].replace("%20", " ")
        if not fname.endswith(".csv"):
            continue
        for t in targets:
            if t in fname:
                full_url = directory_url.rstrip("/") + "/" + link.split("/")[-1]
                matched.append((t, full_url, fname))
                break

    if not matched:
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
            rows = list(reader)
            if len(rows) > 1:
                print(f"  📥 {fname} → {len(rows)-1} records")
                if not all_rows:
                    all_rows.extend(rows)
                else:
                    all_rows.extend(rows[1:])
        except Exception as e:
            print(f"  ❌ {fname}: {e}")

    return all_rows


# ─────────────────────────────────────────────────────────────
# SIGNAL 1: LIS PENDENS
# ─────────────────────────────────────────────────────────────

def scrape_lis_pendens():
    print("\n🔴 Lis Pendens...")
    url = f"{BASE}/CIVIL/LIS_PENDENS_DAILY/"
    rows = fetch_odyssey_csv(url)
    if rows:
        return sheets_helper.append_rows_deduplicated(
            config.SHEETS["lis_pendens"], rows, case_col_index=3)
    print("  ❌ No data")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNAL 2: PROBATE
# Source: PROBATE/NEW_ESTATE_CASE_FILINGS_DAILY/
# Files are Odyssey-style CSVs
# ─────────────────────────────────────────────────────────────

def scrape_probate():
    print("\n🟣 Probate / Estate...")
    url = f"{BASE}/PROBATE/NEW_ESTATE_CASE_FILINGS_DAILY/"
    rows = fetch_odyssey_csv(url, days_back=10)
    if rows:
        return sheets_helper.append_rows_deduplicated(
            config.SHEETS["probate"], rows, case_col_index=1)
    print("  ❌ No probate CSV found - checking directory...")
    # Try fetching directory to see what's there
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = [a.get_text() for a in soup.find_all('a')]
        print(f"  📂 Files in probate dir: {links[:10]}")
    except Exception as e:
        print(f"  ❌ {e}")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNAL 3: EVICTIONS
# ─────────────────────────────────────────────────────────────

def scrape_evictions():
    print("\n🟡 Evictions...")
    url = f"{BASE}/CIVIL/WRIT_OF_POSSESSIONS_DAILY/"
    rows = fetch_odyssey_csv(url)
    if rows:
        return sheets_helper.append_rows_deduplicated(
            config.SHEETS["evictions"], rows, case_col_index=3)
    print("  ❌ No data")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNALS 4 + 5 + 6: LIENS, JUDGMENTS, TAX DEEDS
# Source: OFFICIAL_RECORDS/INDEXES_DAILY/
#
# File prefixes:
#   l = liens  (LNMECH, LNHOA, LNIRS, etc.)
#   d = deeds  (TDEED, DPA, MTG, etc.)
#   m = misc   (mortgages, satisfactions)
#   p = party  (name index — cross-reference)
#
# Format: pipe-delimited
# DocType|County|InstrumentNum|SeqNum|FRM_TO|PartyName
# ─────────────────────────────────────────────────────────────

def scrape_official_records_index():
    print("\n📋 Official Records Index...")

    lien_count = judgment_count = tax_deed_count = 0

    # ── LIEN FILE (l prefix) ──
    print("  🔧 Fetching lien file (l prefix)...")
    lien_records, filed_date = fetch_or_file("l")

    if lien_records:
        # Deduplicate by instrument number — keep one row per instrument
        seen = set()
        unique_liens = []
        unique_judgments = []

        for r in lien_records:
            key = r["instrument"]
            if key in seen or not key:
                continue
            seen.add(key)
            doc = r["doc_type"].upper()
            if any(c in doc for c in LIEN_CODES):
                unique_liens.append(r)
            elif any(c in doc for c in JUDGMENT_CODES):
                unique_judgments.append(r)

        print(f"  🔧 Mechanic/HOA Liens: {len(unique_liens)}")
        print(f"  ⚖️  Judgments: {len(unique_judgments)}")

        cols = ["doc_type", "instrument", "name", "frm_to", "date_filed", "county"]

        if unique_liens:
            sheet_rows = [cols] + [[r.get(c,"") for c in cols] for r in unique_liens]
            lien_count = sheets_helper.append_rows_deduplicated(
                config.SHEETS["mechanic_liens"], sheet_rows, case_col_index=2)

        if unique_judgments:
            sheet_rows = [cols] + [[r.get(c,"") for c in cols] for r in unique_judgments]
            judgment_count = sheets_helper.append_rows_deduplicated(
                config.SHEETS["judgments"], sheet_rows, case_col_index=2)

        # If nothing matched our codes, log what doc types ARE in the file
        if not unique_liens and not unique_judgments:
            doc_types = list(set(r["doc_type"] for r in lien_records[:100]))
            print(f"  ℹ️  Doc types found in l-file: {doc_types[:20]}")

    # ── DEED FILE (d prefix) — Tax Deeds ──
    print("  🏛️  Fetching deed file (d prefix)...")
    deed_records, _ = fetch_or_file("d")

    if deed_records:
        seen = set()
        tax_deeds = []

        for r in deed_records:
            key = r["instrument"]
            if key in seen or not key:
                continue
            seen.add(key)
            doc = r["doc_type"].upper()
            if any(c in doc for c in DEED_CODES):
                tax_deeds.append(r)

        print(f"  🏛️  Tax Deeds: {len(tax_deeds)}")

        if tax_deeds:
            cols = ["doc_type", "instrument", "name", "frm_to", "date_filed", "county"]
            sheet_rows = [cols] + [[r.get(c,"") for c in cols] for r in tax_deeds]
            tax_deed_count = sheets_helper.append_rows_deduplicated(
                config.SHEETS["tax_deeds"], sheet_rows, case_col_index=2)
        else:
            # Log what deed types ARE in the file
            doc_types = list(set(r["doc_type"] for r in deed_records[:200]))
            print(f"  ℹ️  Doc types found in d-file: {doc_types[:20]}")

    return lien_count, judgment_count, tax_deed_count


# ─────────────────────────────────────────────────────────────
# SIGNAL 7: SURPLUS FUNDS
# Source: pinellas.realtdm.com
# ─────────────────────────────────────────────────────────────

def scrape_tax_deeds_and_surplus():
    print("\n💰 Tax Deeds + Surplus (realtdm.com)...")
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        resp = session.get(
            "https://pinellas.realtdm.com/public/cases/list",
            timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "table"})

        if table:
            data_rows    = [["Status","Case Number","Date Created","Parcel Number",
                             "Sale Date","Opening Bid","Surplus Balance","County"]]
            surplus_rows = [["Status","Case Number","Date Created","Parcel Number",
                             "Sale Date","Surplus Balance","County"]]

            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    cells.append("Pinellas")
                    data_rows.append(cells)
                    if len(cells) > 6:
                        bal = str(cells[6]).replace("$","").replace(",","").strip()
                        try:
                            if float(bal) > 0:
                                surplus_rows.append(cells[:7])
                        except Exception:
                            pass

            td = sf = 0
            if len(data_rows) > 1:
                print(f"  📥 {len(data_rows)-1} tax deed records")
                td = sheets_helper.append_rows_deduplicated(
                    config.SHEETS["tax_deeds"], data_rows, case_col_index=2)
            if len(surplus_rows) > 1:
                print(f"  💰 {len(surplus_rows)-1} surplus records")
                sf = sheets_helper.append_rows_deduplicated(
                    config.SHEETS["surplus_funds"], surplus_rows, case_col_index=2)
            return td + sf

    except Exception as e:
        print(f"  ⚠️  realtdm failed: {e}")

    return 0
