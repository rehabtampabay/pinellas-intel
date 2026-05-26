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

# Confirmed doc type codes from Pinellas OR index
LIEN_CODES     = {"LN", "JUD LN"}
JUDGMENT_CODES = {"JUD", "CC JUD", "DRJUDGMENT"}
LP_CODES       = {"LP"}
DEED_CODES     = {"TDEED", "TAXDEED", "CTD", "SRTD"}
PROBATE_D_CODES= {"PROBATE", "PROBATERP"}


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

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


def extract_plaintiff(style):
    """
    Extract the PLAINTIFF (property owner) from 'OWNER VS. TENANT'.
    For evictions the plaintiff IS the landlord — the person we want to call.
    """
    if not style:
        return style, ""
    idx = style.upper().find(" VS. ")
    if idx == -1:
        return style, ""
    plaintiff = style[:idx].strip()
    defendant = re.sub(r'\.?\s*et al\.?$', '', style[idx+5:], flags=re.IGNORECASE).strip()
    return plaintiff, defendant


def extract_defendant(style):
    """
    Extract the DEFENDANT (property owner) from 'BANK VS. OWNER'.
    For lis pendens the defendant is the homeowner being foreclosed on.
    """
    if not style:
        return style, ""
    idx = style.upper().find(" VS. ")
    if idx == -1:
        return style, ""
    plaintiff = style[:idx].strip()
    defendant = re.sub(r'\.?\s*et al\.?$', '', style[idx+5:], flags=re.IGNORECASE).strip()
    return defendant, plaintiff


# ─────────────────────────────────────────────────────────────────
# SIGNAL 1: LIS PENDENS
# Defendant = homeowner being foreclosed on
# ─────────────────────────────────────────────────────────────────

def scrape_lis_pendens():
    print("\nLIS PENDENS...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/LIS_PENDENS_DAILY/")
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["lis_pendens"], rows, dedup_col=3)
    return 0


# ─────────────────────────────────────────────────────────────────
# SIGNAL 2: PROBATE
# ─────────────────────────────────────────────────────────────────

def scrape_probate():
    print("\nPROBATE...")
    rows = fetch_date_format_csv(
        BASE + "/PROBATE/NEW_ESTATE_CASE_FILINGS_DAILY/",
        "EstateNewCaseFilingsDaily_{date}.csv",
        days_back=7, min_size=500)
    if rows:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["probate"], rows,
            dedup_col=1, dedup_col2=4)
    print("  No probate data")
    return 0


# ─────────────────────────────────────────────────────────────────
# SIGNAL 3: EVICTIONS
# Plaintiff = landlord/property owner (the one evicting the tenant)
# We want the PLAINTIFF not the tenant defendant
# Flag this in the sheet so run_all knows to use plaintiff
# ─────────────────────────────────────────────────────────────────

def scrape_evictions():
    print("\nEVICTIONS...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/WRIT_OF_POSSESSIONS_DAILY/")
    if not rows or len(rows) < 2:
        return 0

    # Find the Style column index
    header = rows[0]
    style_col = None
    for i, h in enumerate(header):
        if str(h).upper() in ("STYLE", "STYLE OF CASE"):
            style_col = i
            break

    if style_col is not None:
        # Add an "Owner (Plaintiff)" column after Style
        new_header = header + ["Owner (Plaintiff)", "Tenant (Defendant)"]
        new_rows   = [new_header]
        for row in rows[1:]:
            style = row[style_col] if len(row) > style_col else ""
            plaintiff, defendant = extract_plaintiff(style)
            new_rows.append(row + [plaintiff, defendant])
        rows = new_rows
        print("  Added plaintiff/defendant columns")

    return sheets_helper.append_new_rows(
        SHEET_ID, config.TABS["evictions"], rows, dedup_col=3)


# ─────────────────────────────────────────────────────────────────
# SIGNALS 4+5+6: OFFICIAL RECORDS INDEX
# L-file format (confirmed from logs):
#   col 0  = Instrument number
#   col 4  = Entry type (S=single, A=amendment, JUD=judgment, LN=lien)
#   col 5  = Related instrument
#   col 7  = Book
#   col 8  = Page
#   col 9  = Doc type (JUD, LN, MTG, LP, etc.)
#
# IMPORTANT: The l-file does NOT have party names.
# The p-file (party index) has the names keyed by instrument number.
# We fetch the p-file and build a name lookup table.
# ─────────────────────────────────────────────────────────────────

def build_party_lookup(date_str=None):
    """
    Fetch the p-file (party index) and return a dict:
    {instrument_number: [name1, name2, ...]}
    
    P-file format (confirmed from directory listing):
    p2026051501id.52
    Each line: InstrNum|...|...|...|FRM_or_TO|PartyName|...
    """
    print("  Building party name lookup from p-files (last 7 days)...")
    today  = datetime.today()
    lookup = {}
    loaded = 0

    for i in range(7):
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

            # Print sample from first file found
            if loaded == 0:
                print("  P-file sample (first 3 lines):")
                for ln in lines[:3]:
                    print("    " + ln[:120])

            # Accumulate all days into one lookup
            for line in lines:
                parts = line.split("|")
                if len(parts) < 6:
                    continue
                instrument = parts[2].strip()
                party_name = parts[5].strip() if len(parts) > 5 else ""
                frm_to     = parts[4].strip() if len(parts) > 4 else ""

                if instrument and party_name:
                    if instrument not in lookup:
                        lookup[instrument] = []
                    # Prefer FRM (grantor/debtor) = the property owner/debtor
                    if frm_to.upper() in ("FRM", "FROM", "GRANTOR", "DEBTOR"):
                        lookup[instrument].insert(0, party_name)
                    else:
                        lookup[instrument].append(party_name)
            loaded += 1

        except Exception as e:
            print("  " + fname + ": " + str(e))

    if lookup:
        print("  P-files loaded: " + str(loaded) + " days | " +
              str(len(lookup)) + " instruments indexed")
    else:
        print("  No p-file data found — names will be blank")
    return lookup


def scrape_official_records_index():
    print("\nOFFICIAL RECORDS INDEX...")
    lien_count = judgment_count = tax_deed_count = lp_count = 0

    # Build party name lookup first
    party_lookup = build_party_lookup()

    # ── L-FILE: liens, judgments, LP ──
    lines, filed_date = fetch_or_raw("l")
    if lines:
        lien_rows = [["Instrument", "Owner / Party", "Doc Type",
                       "Book", "Page", "Date Filed"]]
        jud_rows  = [["Instrument", "Owner / Party", "Doc Type",
                       "Book", "Page", "Date Filed"]]
        lp_rows   = [["Instrument", "Owner / Party", "Doc Type",
                       "Book", "Page", "Date Filed"]]
        seen      = set()
        all_types = set()

        for line in lines:
            parts = line.split("|")
            if len(parts) < 10:
                continue
            instrument = parts[0].strip()
            doc_type   = parts[9].strip()
            doc_upper  = doc_type.upper()
            book       = parts[7].strip() if len(parts) > 7 else ""
            page       = parts[8].strip() if len(parts) > 8 else ""
            all_types.add(doc_type)

            if not instrument or instrument in seen:
                continue
            seen.add(instrument)

            # Look up party name
            names = party_lookup.get(instrument, [])
            owner = names[0] if names else ""

            row = [instrument, owner, doc_type, book, page, filed_date]

            if doc_upper in LP_CODES:
                lp_rows.append(row)
            elif doc_upper in LIEN_CODES or (
                    doc_upper.startswith("LN") and "JUD" not in doc_upper):
                lien_rows.append(row)
            elif doc_upper in JUDGMENT_CODES or "JUD" in doc_upper:
                jud_rows.append(row)

        print("  Doc types: " + str(sorted(all_types)))
        print("  LP: " + str(len(lp_rows)-1) +
              " | Liens: " + str(len(lien_rows)-1) +
              " | Judgments: " + str(len(jud_rows)-1))

        if len(lp_rows) > 1:
            lp_count = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["lis_pendens"], lp_rows, dedup_col=1)

        if len(lien_rows) > 1:
            lien_count = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["mechanic_liens"], lien_rows, dedup_col=1)

        if len(jud_rows) > 1:
            judgment_count = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["judgments"], jud_rows, dedup_col=1)

    # ── D-FILE: deeds, tax deeds, probate recordings ──
    print("  Fetching d-file...")
    d_lines, d_date = fetch_or_raw("d")
    if d_lines:
        deed_rows    = [["Instrument", "Owner / Party", "Doc Type",
                          "Description", "Date Filed"]]
        probate_rows = [["Instrument", "Owner / Party", "Doc Type",
                          "Description", "Date Filed"]]
        seen         = set()
        all_d_types  = set()

        for line in d_lines:
            parts = line.split("|")
            if len(parts) < 4:
                continue
            instrument  = parts[2].strip()
            doc_type    = parts[3].strip()
            doc_upper   = doc_type.upper()
            description = parts[4].strip() if len(parts) > 4 else ""
            date_filed  = parts[11].strip() if len(parts) > 11 else (d_date or "")
            all_d_types.add(doc_type)

            if not instrument or instrument in seen:
                continue
            seen.add(instrument)

            names = party_lookup.get(instrument, [])
            owner = names[0] if names else ""

            row = [instrument, owner, doc_type, description, date_filed]

            if doc_upper in DEED_CODES or "TDEED" in doc_upper:
                deed_rows.append(row)
            elif doc_upper in PROBATE_D_CODES:
                probate_rows.append(row)

        print("  D-file types (sample): " + str(sorted(all_d_types)[:15]))
        print("  Tax deeds: " + str(len(deed_rows)-1) +
              " | Probate recordings: " + str(len(probate_rows)-1))

        if len(deed_rows) > 1:
            tax_deed_count = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["tax_deeds"], deed_rows, dedup_col=1)

        if len(probate_rows) > 1:
            p_added = sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["probate"], probate_rows, dedup_col=1)
            print("  + " + str(p_added) + " probate recordings from OR")

    return lien_count + lp_count, judgment_count, tax_deed_count


# ─────────────────────────────────────────────────────────────────
# SIGNAL 7: NEW CASE FILINGS
# ─────────────────────────────────────────────────────────────────

def scrape_new_case_filings():
    print("\nNEW CASE FILINGS...")
    rows = fetch_odyssey_csv(BASE + "/CIVIL/NEW_CASE_FILINGS_DAILY/")
    if not rows or len(rows) < 2:
        print("  No data")
        return 0, 0

    header = rows[0]
    ct_col = next((i for i, h in enumerate(header)
                   if "CASE TYPE" in str(h).upper()), None)
    if ct_col is None:
        return 0, 0

    jud_rows = [header]
    tax_rows = [header]
    for row in rows[1:]:
        if len(row) <= ct_col:
            continue
        ct = row[ct_col].upper()
        if any(x in ct for x in ["JUDGMENT", "GARNISH", "SMALL CLAIM"]):
            jud_rows.append(row)
        elif any(x in ct for x in ["TAX DEED", "TAXDEED", "TAX CERT"]):
            tax_rows.append(row)

    jud_added = tax_added = 0
    if len(jud_rows) > 1:
        jud_added = sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["judgments"], jud_rows, dedup_col=3)
    if len(tax_rows) > 1:
        tax_added = sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["tax_deeds"], tax_rows, dedup_col=3)
    return jud_added, tax_added


# ─────────────────────────────────────────────────────────────────
# SIGNAL 8: SURPLUS FUNDS
# ─────────────────────────────────────────────────────────────────

def scrape_surplus_funds():
    print("\nSURPLUS FUNDS...")
    reg_url = BASE + "/CIVIL/REGISTRY_TRUST_BALANCES_DAILY/"
    try:
        resp = requests.get(reg_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        pdf_links = [a["href"] for a in soup.find_all("a", href=True)
                     if a["href"].lower().endswith(".pdf")]
        today   = datetime.today()
        targets = []
        for i in range(7):
            d = today - timedelta(days=i)
            targets.append(d.strftime("%B %d, %Y"))
            try:
                targets.append(d.strftime("%B %-d, %Y"))
            except Exception:
                pass
        recent = [l.split("/")[-1].replace("%20"," ")
                  for l in pdf_links
                  if any(t in l.replace("%20"," ") for t in targets)]
        if recent:
            print("  Recent registry files: " + str(recent[:3]))
            rows = [["Source File", "Date", "Note", "County"],
                    [recent[0], today.strftime("%m/%d/%Y"),
                     "Registry Trust Balance PDF — review at Pinellas Clerk",
                     "Pinellas"]]
            return sheets_helper.append_new_rows(
                SHEET_ID, config.TABS["surplus_funds"], rows, dedup_col=1)
    except Exception as e:
        print("  Registry error: " + str(e))

    # Fallback: garnishment weekly
    rows = fetch_odyssey_csv(
        BASE + "/CIVIL/CIVIL_WITH_SERVICE_AND_GARNISHMENT_WEEKLY/",
        days_back=10)
    if rows and len(rows) > 1:
        return sheets_helper.append_new_rows(
            SHEET_ID, config.TABS["surplus_funds"], rows, dedup_col=3)

    print("  No surplus data")
    return 0


def scrape_tax_deeds_and_surplus():
    return 0
