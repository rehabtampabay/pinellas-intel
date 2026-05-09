# ================================================================
# PINELLAS COUNTY SCRAPER
# Pulls from publicfiles.mypinellasclerk.gov
# Writes to Pinellas Courthouse Leads Master spreadsheet
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

HEADERS    = {"User-Agent": "Mozilla/5.0 (compatible; PropertyIntel/1.0)"}
BASE       = config.COUNTIES["pinellas"]["public_base"]
SHEET_ID   = config.COUNTIES["pinellas"]["sheet_id"]

# Official Records doc type codes
LIEN_CODES     = {"LNMECH", "LNHOA", "LNIRS", "LNCTY", "LNSTA", "LNCON"}
JUDGMENT_CODES = {"JUD", "CCJ", "DRJUD", "JUDL", "FJUD", "JUDO"}
DEED_CODES     = {"TDEED", "TAXDEED", "CTD", "SRTD"}


# ── HELPER: Download Odyssey-style CSV from a daily directory ────

def fetch_odyssey_csv(directory_url, days_back=7):
    """
    Hits a Pinellas public files directory listing,
    finds CSVs from the last N days, returns parsed rows.
    Starts from yesterday (day 1) since files are generated overnight.
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
    for i in range(1, days_back + 1):   # start at 1 = yesterday
        d = today - timedelta(days=i)
        targets.append(d.strftime("%B %d, %Y"))
        targets.append(d.strftime("%B %-d, %Y"))

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
        print("  No recent CSV files found in " + directory_url)
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
                print("  Downloaded " + fname + " — " + str(len(rows) - 1) + " records")
                if not all_rows:
                    all_rows.extend(rows)
                else:
                    all_rows.extend(rows[1:])  # skip header on subsequent files
        except Exception as e:
            print("  Error reading " + fname + ": " + str(e))

    return all_rows


# ── HELPER: Download pipe-delimited Official Records index ───────

def fetch_or_file(prefix, days_back=5):
    """
    Downloads the pipe-delimited Official Records index file.
    File naming: {prefix}YYYYMMDD01id.52
    Starts from yesterday since files are generated overnight.
    """
    today = datetime.today()
    for i in range(1, days_back + 1):   # start at 1 = yesterday
        date  = today - timedelta(days=i)
        fname = prefix + date.strftime("%Y%m%d") + "01id.52"
        url   = BASE + "/OFFICIAL_RECORDS/INDEXES_DAILY/" + fname
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
                        "doc_type":    parts[0].strip(),
                        "county_code": parts[1].strip(),
                        "instrument":  parts[2].strip(),
                        "seq":         parts[3].strip(),
                        "frm_to":      parts[4].strip(),
                        "name":        parts[5].strip() if len(parts) > 5 else "",
                        "date_filed":  date.strftime("%Y-%m-%d"),
                    })

            if rows:
                print("  Downloaded " + fname + " — " + str(len(rows)) + " raw lines")
                return rows

        except Exception as e:
            print("  " + fname + ": " + str(e))

    return []


# ── SIGNAL 1: LIS PENDENS ────────────────────────────────────────

def scrape_lis_pendens():
    print("\nLIS PENDENS...")
    url  = BASE + "/CIVIL/LIS_PENDENS_DAILY/"
    rows = fetch_odyssey_csv(url)
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID,
            config.TABS["lis_pendens"],
            rows,
            dedup_col=3
        )
    print("  No data found")
    return 0


# ── SIGNAL 2: PROBATE ────────────────────────────────────────────

def scrape_probate():
    print("\nPROBATE...")
    url  = BASE + "/PROBATE/NEW_ESTATE_CASE_FILINGS_DAILY/"
    rows = fetch_odyssey_csv(url)
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID,
            config.TABS["probate"],
            rows,
            dedup_col=1
        )
    # Log what files are actually in the directory
    try:
        resp  = requests.get(url, headers=HEADERS, timeout=15)
        soup  = BeautifulSoup(resp.text, "html.parser")
        files = [a.get_text() for a in soup.find_all("a")]
        print("  Files in probate dir: " + str(files[:10]))
    except Exception:
        pass
    print("  No probate data found")
    return 0


# ── SIGNAL 3: EVICTIONS ──────────────────────────────────────────

def scrape_evictions():
    print("\nEVICTIONS...")
    url  = BASE + "/CIVIL/WRIT_OF_POSSESSIONS_DAILY/"
    rows = fetch_odyssey_csv(url)
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID,
            config.TABS["evictions"],
            rows,
            dedup_col=3
        )
    print("  No data found")
    return 0


# ── SIGNALS 4+5+6: OFFICIAL RECORDS INDEX ───────────────────────
# l-file = liens (LNMECH, LNHOA, LNIRS...)
# d-file = deeds (TDEED, DPA...)

def scrape_official_records_index():
    print("\nOFFICIAL RECORDS INDEX...")

    lien_count = judgment_count = tax_deed_count = 0

    # ── Lien file ──
    print("  Fetching lien file (l-prefix)...")
    lien_records = fetch_or_file("l")

    if lien_records:
        seen      = set()
        liens     = []
        judgments = []

        for r in lien_records:
            key = r["instrument"]
            if not key or key in seen:
                continue
            seen.add(key)
            doc = r["doc_type"].upper()
            if any(c in doc for c in LIEN_CODES):
                liens.append(r)
            elif any(c in doc for c in JUDGMENT_CODES):
                judgments.append(r)

        print("  Mechanic/HOA Liens: " + str(len(liens)))
        print("  Judgments: " + str(len(judgments)))

        # Log actual doc types if nothing matched
        if not liens and not judgments:
            found = list(set(r["doc_type"] for r in lien_records[:100]))
            print("  Doc types in l-file: " + str(found[:20]))

        cols = ["doc_type", "instrument", "name", "frm_to", "date_filed"]

        if liens:
            sheet_rows = [cols] + [[r.get(c, "") for c in cols] for r in liens]
            lien_count = sheets_helper.append_new_rows(
                SHEET_ID,
                config.TABS["mechanic_liens"],
                sheet_rows,
                dedup_col=2
            )

        if judgments:
            sheet_rows = [cols] + [[r.get(c, "") for c in cols] for r in judgments]
            judgment_count = sheets_helper.append_new_rows(
                SHEET_ID,
                config.TABS["judgments"],
                sheet_rows,
                dedup_col=2
            )

    # ── Deed file ──
    print("  Fetching deed file (d-prefix)...")
    deed_records = fetch_or_file("d")

    if deed_records:
        seen      = set()
        tax_deeds = []

        for r in deed_records:
            key = r["instrument"]
            if not key or key in seen:
                continue
            seen.add(key)
            doc = r["doc_type"].upper()
            if any(c in doc for c in DEED_CODES):
                tax_deeds.append(r)

        print("  Tax Deeds: " + str(len(tax_deeds)))

        if not tax_deeds:
            found = list(set(r["doc_type"] for r in deed_records[:200]))
            print("  Doc types in d-file: " + str(found[:20]))

        if tax_deeds:
            cols = ["doc_type", "instrument", "name", "frm_to", "date_filed"]
            sheet_rows = [cols] + [[r.get(c, "") for c in cols] for r in tax_deeds]
            tax_deed_count = sheets_helper.append_new_rows(
                SHEET_ID,
                config.TABS["tax_deeds"],
                sheet_rows,
                dedup_col=2
            )

    return lien_count, judgment_count, tax_deed_count


# ── SIGNAL 7: TAX DEEDS + SURPLUS (realtdm.com) ─────────────────

def scrape_tax_deeds_and_surplus():
    print("\nTAX DEEDS + SURPLUS (realtdm)...")
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        resp  = session.get("https://pinellas.realtdm.com/public/cases/list", timeout=30)
        soup  = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "table"})

        if not table:
            print("  No table found on realtdm — site may block scrapers")
            return 0

        header    = ["Status", "Case Number", "Date Created", "Parcel Number",
                     "Sale Date", "Opening Bid", "Surplus Balance", "County"]
        tax_rows  = [header]
        surp_rows = [header]

        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if not cells:
                continue
            cells.append("Pinellas")
            tax_rows.append(cells)
            # Surplus = positive balance
            if len(cells) > 6:
                bal = str(cells[6]).replace("$", "").replace(",", "").strip()
                try:
                    if float(bal) > 0:
                        surp_rows.append(cells)
                except Exception:
                    pass

        td = sf = 0
        if len(tax_rows) > 1:
            print("  " + str(len(tax_rows) - 1) + " tax deed records")
            td = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["tax_deeds"], tax_rows, dedup_col=2)

        if len(surp_rows) > 1:
            print("  " + str(len(surp_rows) - 1) + " surplus records")
            sf = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["surplus_funds"], surp_rows, dedup_col=2)

        return td + sf

    except Exception as e:
        print("  realtdm failed: " + str(e))
        return 0
