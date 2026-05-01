"""
Pinellas County Unified Scraper
Signals: Lis Pendens, Probate, Evictions, Mechanic Liens, Judgments, Tax Deeds, Surplus Funds
Source: publicfiles.mypinellasclerk.gov + pinellas.realtdm.com
"""

import requests
import re
import csv
import io
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import sheets_helper
import config

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PropertyIntel/1.0)"}

# ─────────────────────────────────────────────────────────────
# HELPER: Download CSV files from Pinellas public files server
# ─────────────────────────────────────────────────────────────

def fetch_csv_from_directory(directory_url, filename_pattern, days_back=10):
    """
    Hits a Pinellas public files directory, finds CSVs matching pattern
    for the last N days, and returns them as parsed rows.
    """
    try:
        resp = requests.get(directory_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ Could not reach {directory_url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links = [a['href'] for a in soup.find_all('a', href=True)]

    today = datetime.today()
    target_dates = [(today - timedelta(days=i)).strftime("%B %d, %Y") for i in range(days_back)]

    matched = []
    for link in links:
        fname = link.split("/")[-1]
        for date_str in target_dates:
            if date_str in fname and re.search(filename_pattern, fname):
                matched.append((date_str, directory_url.rstrip("/") + "/" + fname, fname))
                break

    all_rows = []
    for date_str, url, fname in sorted(matched, reverse=True)[:3]:  # Max 3 files
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if not r.ok or len(r.content) < 500:
                print(f"  ⚠️  {fname} too small or failed — skipping")
                continue
            reader = csv.reader(io.StringIO(r.text))
            rows = list(reader)
            if len(rows) > 1:
                print(f"  📥 {fname} → {len(rows)-1} records")
                all_rows.extend(rows if not all_rows else rows[1:])
        except Exception as e:
            print(f"  ❌ Error reading {fname}: {e}")

    return all_rows


def fetch_csv_by_date_format(base_url, fname_template, days_back=10):
    """
    For files named by MM-DD-YYYY format (probate style).
    """
    today = datetime.today()
    all_rows = []

    for i in range(days_back):
        date = today - timedelta(days=i)
        fname = fname_template.format(date=date.strftime("%m-%d-%Y"))
        url = base_url.rstrip("/") + "/" + fname
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if not r.ok or len(r.content) < 500:
                continue
            reader = csv.reader(io.StringIO(r.text))
            rows = list(reader)
            if len(rows) > 1:
                print(f"  📥 {fname} → {len(rows)-1} records")
                all_rows.extend(rows if not all_rows else rows[1:])
                break  # Got one, stop
        except Exception as e:
            print(f"  ❌ Error: {e}")

    return all_rows


# ─────────────────────────────────────────────────────────────
# SIGNAL 1: LIS PENDENS (Pre-Foreclosure)
# ─────────────────────────────────────────────────────────────

def scrape_lis_pendens():
    print("\n🔍 Lis Pendens...")
    url = f"{config.PINELLAS_PUBLIC_BASE}/CIVIL/LIS_PENDENS_DAILY/"
    rows = fetch_csv_from_directory(url, r"Odyssey-JobOutput.*-2\.csv")
    if rows:
        added = sheets_helper.append_rows_deduplicated(config.SHEETS["lis_pendens"], rows, case_col_index=3)
        return added
    print("  ❌ No Lis Pendens data found")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNAL 2: PROBATE / ESTATE
# ─────────────────────────────────────────────────────────────

def scrape_probate():
    print("\n🔍 Probate / Estate...")
    url = f"{config.PINELLAS_PUBLIC_BASE}/PROBATE/NEW_ESTATE_CASE_FILINGS_DAILY/"
    rows = fetch_csv_by_date_format(url, "EstateNewCaseFilingsDaily_{date}.csv")
    if rows:
        added = sheets_helper.append_rows_deduplicated(config.SHEETS["probate"], rows, case_col_index=1)
        return added
    print("  ❌ No Probate data found")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNAL 3: EVICTIONS (Writ of Possession = tenant can't pay)
# ─────────────────────────────────────────────────────────────

def scrape_evictions():
    print("\n🔍 Evictions (Writ of Possession)...")
    url = f"{config.PINELLAS_PUBLIC_BASE}/CIVIL/WRIT_OF_POSSESSIONS_DAILY/"
    rows = fetch_csv_from_directory(url, r"Odyssey-JobOutput.*-2\.csv")
    if rows:
        added = sheets_helper.append_rows_deduplicated(config.SHEETS["evictions"], rows, case_col_index=3)
        return added
    print("  ❌ No Eviction data found")
    return 0


# ─────────────────────────────────────────────────────────────
# SIGNAL 4: MECHANIC LIENS
# ─────────────────────────────────────────────────────────────

def scrape_mechanic_liens():
    print("\n🔍 Mechanic Liens...")
    # Try the direct CSV endpoint first
    for path_guess in [
        "/CIVIL/MECHANIC_LIENS_DAILY/",
        "/CIVIL/LIEN_FILINGS_DAILY/",
        "/CIVIL/LIENS_DAILY/",
    ]:
        url = f"{config.PINELLAS_PUBLIC_BASE}{path_guess}"
        rows = fetch_csv_from_directory(url, r"Odyssey-JobOutput.*-2\.csv")
        if rows:
            added = sheets_helper.append_rows_deduplicated(config.SHEETS["mechanic_liens"], rows, case_col_index=3)
            return added

    # Fallback: Official Records search for LNMECH doc type
    rows = scrape_official_records(doc_type="LNMECH", tab_key="mechanic_liens")
    return rows


# ─────────────────────────────────────────────────────────────
# SIGNAL 5: JUDGMENTS
# ─────────────────────────────────────────────────────────────

def scrape_judgments():
    print("\n🔍 Judgments...")
    for path_guess in [
        "/CIVIL/JUDGMENTS_DAILY/",
        "/CIVIL/JUDGMENT_FILINGS_DAILY/",
    ]:
        url = f"{config.PINELLAS_PUBLIC_BASE}{path_guess}"
        rows = fetch_csv_from_directory(url, r"Odyssey-JobOutput.*-2\.csv")
        if rows:
            added = sheets_helper.append_rows_deduplicated(config.SHEETS["judgments"], rows, case_col_index=3)
            return added

    rows = scrape_official_records(doc_type="JUD", tab_key="judgments")
    return rows


# ─────────────────────────────────────────────────────────────
# SIGNAL 6: TAX DEEDS + SURPLUS FUNDS
# Source: pinellas.realtdm.com (requests-based, no Selenium)
# ─────────────────────────────────────────────────────────────

def scrape_tax_deeds_and_surplus():
    print("\n🔍 Tax Deeds + Surplus Funds...")

    base = "https://pinellas.realtdm.com"
    session = requests.Session()
    session.headers.update(HEADERS)

    # Try the API endpoint that the website uses internally
    try:
        today = datetime.today()
        start = (today - timedelta(days=180)).strftime("%m/%d/%Y")
        end = today.strftime("%m/%d/%Y")

        # The site uses a JSON API under the hood
        api_url = f"{base}/public/cases/search"
        payload = {
            "saleDateStart": start,
            "saleDateEnd": end,
            "statusFilters": [],
            "page": 1,
            "pageSize": 500
        }

        resp = session.post(api_url, json=payload, timeout=30)

        if resp.ok and resp.text.startswith("[") or (resp.ok and "cases" in resp.text.lower()):
            data = resp.json()
            cases = data if isinstance(data, list) else data.get("cases", data.get("data", []))

            if cases:
                print(f"  📥 {len(cases)} tax deed records via API")
                tax_deed_rows = [["Status", "Case Number", "Date Created", "Parcel Number", "Sale Date", "Opening Bid", "Surplus Balance", "County", "Score"]]
                surplus_rows = [["Status", "Case Number", "Date Created", "Parcel Number", "Sale Date", "Surplus Balance", "County"]]

                for c in cases:
                    row = [
                        c.get("status", ""),
                        c.get("caseNumber", c.get("case_number", "")),
                        c.get("dateCreated", c.get("created", "")),
                        c.get("parcelNumber", c.get("parcel", "")),
                        c.get("saleDate", c.get("sale_date", "")),
                        c.get("openingBid", c.get("opening_bid", "")),
                        c.get("surplusBalance", c.get("surplus", "")),
                        "Pinellas",
                        ""
                    ]
                    tax_deed_rows.append(row)

                    surplus_bal = str(row[6]).replace("$", "").replace(",", "").strip()
                    if surplus_bal and float(surplus_bal or 0) > 0:
                        surplus_rows.append(row[:7])

                td_added = sheets_helper.append_rows_deduplicated(config.SHEETS["tax_deeds"], tax_deed_rows, case_col_index=2)
                sf_added = sheets_helper.append_rows_deduplicated(config.SHEETS["surplus_funds"], surplus_rows, case_col_index=2)
                return td_added + sf_added

    except Exception as e:
        print(f"  ⚠️  API attempt failed: {e}")

    # Fallback: scrape the HTML table
    try:
        resp = session.get(f"{base}/public/cases/list", timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "table"})
        if table:
            rows_html = table.find_all("tr")
            data_rows = [["Status", "Case Number", "Date Created", "Parcel Number", "Sale Date", "Opening Bid", "Surplus Balance", "County"]]
            for tr in rows_html[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    cells.append("Pinellas")
                    data_rows.append(cells)
            if len(data_rows) > 1:
                print(f"  📥 {len(data_rows)-1} records via HTML fallback")
                return sheets_helper.append_rows_deduplicated(config.SHEETS["tax_deeds"], data_rows, case_col_index=2)
    except Exception as e:
        print(f"  ❌ HTML fallback also failed: {e}")

    print("  ⚠️  Tax deeds site may require browser — check manually at pinellas.realtdm.com")
    return 0


# ─────────────────────────────────────────────────────────────
# FALLBACK: Official Records Search (for liens, judgments)
# ─────────────────────────────────────────────────────────────

def scrape_official_records(doc_type, tab_key):
    """
    Searches Pinellas Clerk Official Records for a specific document type
    filed in the last 10 days.
    """
    print(f"  📡 Trying Official Records search for {doc_type}...")
    today = datetime.today()
    from_date = (today - timedelta(days=10)).strftime("%m/%d/%Y")
    to_date = today.strftime("%m/%d/%Y")

    # Pinellas Clerk OR search endpoint
    search_url = "https://www.pinellasclerk.org/ASPIncludes2/officialRecordsResults.asp"
    params = {
        "docType": doc_type,
        "fromDate": from_date,
        "toDate": to_date,
        "submit": "Search"
    }

    try:
        resp = requests.get(search_url, params=params, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            print(f"  ⚠️  No results table found for {doc_type}")
            return 0

        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)

        if len(rows) > 1:
            added = sheets_helper.append_rows_deduplicated(config.SHEETS[tab_key], rows, case_col_index=2)
            return added
    except Exception as e:
        print(f"  ❌ Official Records search failed: {e}")

    return 0
