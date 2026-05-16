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

# L-file: col 9 is doc type
LIEN_CODES     = {"LN","LNMECH","LNHOA","LNIRS","LNCTY","LNCON","LNSTA","LNFED","LNTAX"}
JUDGMENT_CODES = {"JUD","CCJ","DRJUD","FJUD","JUDO","JUDL","SATJUD"}
# D-file: col 3 is doc type
DEED_CODES     = {"TDEED","TAXDEED","CTD","SRTD"}


def fetch_odyssey_csv(directory_url, days_back=7):
    try:
        resp = requests.get(directory_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print("  Could not reach " + directory_url + ": " + str(e))
        return []

    soup  = BeautifulSoup(resp.text, "html.parser")
    links = [a["href"] for a in soup.find_all("a", href=True)]
    today = datetime.today()
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


def fetch_date_format_csv(base_url, template, days_back=7, min_size=500):
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


def fetch_or_raw(prefix, days_back=5):
    today = datetime.today()
    for i in range(days_back):
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
            lines = [l for l in text.strip().splitlines() if "|" in l]
            if lines:
                print("  Downloaded " + fname + " — " + str(len(lines)) + " lines")
                return lines, date.strftime("%m/%d/%Y")
        except Exception as e:
            print("  " + fname + ": " + str(e))
    return [], None


def scrape_lis_pendens():
    print("\nLIS PENDENS...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/LIS_PENDENS_DAILY/")
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["lis_pendens"], rows, dedup_col=3)
    return 0


def scrape_probate():
    print("\nPROBATE...")
    rows = fetch_date_format_csv(
        BASE + "/PROBATE/NEW_ESTATE_CASE_FILINGS_DAILY/",
        "EstateNewCaseFilingsDaily_{date}.csv",
        days_back=7, min_size=500)
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["probate"], rows, dedup_col=1)
    print("  No probate data")
    return 0


def scrape_evictions():
    print("\nEVICTIONS...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/WRIT_OF_POSSESSIONS_DAILY/")
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["evictions"], rows, dedup_col=3)
    return 0


def scrape_official_records_index():
    print("\nOFFICIAL RECORDS INDEX...")
    lien_count = judgment_count = tax_deed_count = 0

    # L-FILE: col 0=instrument, col 9=doc type, col 7=book, col 8=page
    lines, filed_date = fetch_or_raw("l")
    if lines:
        print("  L-file sample (first 3 lines):")
        for ln in lines[:3]:
            print("    " + ln[:120])

        lien_rows = [["Instrument", "Doc Type", "Book", "Page", "Date Filed"]]
        jud_rows  = [["Instrument", "Doc Type", "Book", "Page", "Date Filed"]]
        seen      = set()
        all_types = set()

        for line in lines:
            parts = line.split("|")
            if len(parts) < 10:
                continue
            instrument = parts[0].strip()
            doc_type   = parts[9].strip().upper()
            book       = parts[7].strip() if len(parts) > 7 else ""
            page       = parts[8].strip() if len(parts) > 8 else ""
            all_types.add(doc_type)

            if not instrument or instrument in seen:
                continue
            seen.add(instrument)

            if doc_type in LIEN_CODES or doc_type.startswith("LN"):
                lien_rows.append([instrument, doc_type, book, page, filed_date])
            elif doc_type in JUDGMENT_CODES or "JUD" in doc_type:
                jud_rows.append([instrument, doc_type, book, page, filed_date])

        print("  Doc types in l-file: " + str(sorted(all_types)))
        print("  Liens: " + str(len(lien_rows)-1))
        print("  Judgments: " + str(len(jud_rows)-1))

        if len(lien_rows) > 1:
            lien_count = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["mechanic_liens"], lien_rows, dedup_col=1)
        if len(jud_rows) > 1:
            judgment_count = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["judgments"], jud_rows, dedup_col=1)

    # D-FILE: col 2=instrument, col 3=doc type, col 4=desc, col 5=legal, col 11=date
    print("  Fetching d-file...")
    d_lines, d_date = fetch_or_raw("d")
    if d_lines:
        print("  D-file sample (first 3 lines):")
        for ln in d_lines[:3]:
            print("    " + ln[:120])

        deed_rows = [["Instrument", "Doc Type", "Description", "Legal Desc", "Date Filed"]]
        seen      = set()
        all_d_types = set()

        for line in d_lines:
            parts = line.split("|")
            if len(parts) < 4:
                continue
            instrument  = parts[2].strip()
            doc_type    = parts[3].strip().upper()
            description = parts[4].strip() if len(parts) > 4 else ""
            legal_desc  = parts[5].strip() if len(parts) > 5 else ""
            date_filed  = parts[11].strip() if len(parts) > 11 else (d_date or "")
            all_d_types.add(doc_type)

            if not instrument or instrument in seen:
                continue
            seen.add(instrument)

            if doc_type in DEED_CODES or "TDEED" in doc_type or "TAX" in doc_type:
                deed_rows.append([instrument, doc_type, description, legal_desc, date_filed])

        print("  Doc types in d-file: " + str(sorted(all_d_types)))
        print("  Tax deeds: " + str(len(deed_rows)-1))

        if len(deed_rows) > 1:
            tax_deed_count = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["tax_deeds"], deed_rows, dedup_col=1)

    return lien_count, judgment_count, tax_deed_count


def scrape_new_case_filings():
    print("\nNEW CASE FILINGS...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/NEW_CASE_FILINGS_DAILY/")
    if not rows or len(rows) < 2:
        print("  No data")
        return 0, 0

    header = rows[0]
    print("  Columns: " + str(header[:8]))

    ct_col = None
    for i, h in enumerate(header):
        if "CASE TYPE" in str(h).upper():
            ct_col = i
            break

    if ct_col is None:
        print("  No Case Type column — all cols: " + str(header))
        return 0, 0

    jud_rows = [header]
    tax_rows = [header]
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


def scrape_surplus_funds():
    print("\nSURPLUS FUNDS...")
    reg_url = BASE + "/CIVIL/REGISTRY_TRUST_BALANCES_DAILY/"
    try:
        resp  = requests.get(reg_url, headers=HEADERS, timeout=15)
        soup  = BeautifulSoup(resp.text, "html.parser")
        files = [a.get_text().strip() for a in soup.find_all("a") if a.get_text().strip()]
        print("  Files in registry dir: " + str(files[:10]))
        links = [a["href"] for a in soup.find_all("a", href=True)
                 if a["href"].lower().endswith(".csv")]
        if links:
            url = reg_url.rstrip("/") + "/" + links[0].split("/")[-1]
            r   = requests.get(url, headers=HEADERS, timeout=15)
            if r.ok and len(r.content) > 300:
                try:
                    text = r.content.decode("utf-8")
                except UnicodeDecodeError:
                    text = r.content.decode("latin-1")
                reader = csv.reader(io.StringIO(text))
                rows   = list(reader)
                if len(rows) > 1:
                    print("  Columns: " + str(rows[0][:8]))
                    return sheets_helper.append_new_rows(
                        SHEET_ID, config.TABS["surplus_funds"], rows, dedup_col=3)
    except Exception as e:
        print("  Registry error: " + str(e))

    # Fallback: weekly garnishment file
    print("  Trying garnishment weekly file...")
    rows = fetch_odyssey_csv(
        BASE + "/CIVIL/CIVIL_WITH_SERVICE_AND_GARNISHMENT_WEEKLY/", days_back=10)
    if rows and len(rows) > 1:
        header = rows[0]
        print("  Garnishment columns: " + str(header[:8]))
        ct_col = None
        for i, h in enumerate(header):
            if "CASE TYPE" in str(h).upper():
                ct_col = i
                break
        if ct_col:
            garni = [header] + [r for r in rows[1:]
                     if len(r) > ct_col and "GARNISH" in r[ct_col].upper()]
            if len(garni) > 1:
                print("  Garnishment records: " + str(len(garni)-1))
                return sheets_helper.append_new_rows(
                    SHEET_ID, config.TABS["surplus_funds"], garni, dedup_col=3)
        else:
            # Push all weekly records as surplus signals
            print("  Pushing all " + str(len(rows)-1) + " weekly service records")
            return sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["surplus_funds"], rows, dedup_col=3)

    print("  No surplus data found")
    return 0


def scrape_tax_deeds_and_surplus():
    return 0
