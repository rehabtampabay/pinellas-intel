# ─────────────────────────────────────────────────────────────────────────────
# scrapers/hillsborough.py  —  Hillsborough County lead scraper
#
# Data source: publicrec.hillsclerk.com  (free, no auth required)
#
# Files published daily at midnight for the PREVIOUS day's filings.
# Weekends produce a tiny placeholder file (~151 bytes) — skipped automatically.
#
# Civil file columns (tab-separated):
#   CaseCategory | CaseTypeDescription | CaseNumber | Title | FilingDate |
#   PartyType | FirstName | MiddleName | LastName/CompanyName | PartyAddress | Attorney
#
# Probate file columns (tab-separated):
#   CaseCategory | CaseTypeDescription | CaseNumber | Title | FilingDate |
#   PartyType | FirstName | MiddleName | LastName/CompanyName | DateofDeath | PartyAddress | Attorney
#
# Strategy:
#   - Each case has MULTIPLE rows (one per party). We group by CaseNumber.
#   - For lis pendens / judgments: extract the Defendant row (property owner).
#   - For evictions: extract the Plaintiff row (landlord = property owner).
#   - For probate: extract the Decedent row for name, Petitioner for contact.
#   - On first run (empty sheet tab): backfill last BACKFILL_DAYS weekdays.
#   - On subsequent runs: download yesterday's file only.
# ─────────────────────────────────────────────────────────────────────────────

import csv
import io
import os
import sys
import time
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import sheets_helper

# ── URL templates ─────────────────────────────────────────────────────────────
CIVIL_URL   = "https://publicrec.hillsclerk.com/Civil/dailyfilings/CivilFiling_{date}.csv"
PROBATE_URL = "https://publicrec.hillsclerk.com/Probate/dailyfilings/ProbateFiling_{date}.csv"

HEADERS       = {"User-Agent": "Mozilla/5.0 (compatible; PropertyIntelBot/1.0)"}
BACKFILL_DAYS = 30
MIN_FILE_BYTES = 300   # files smaller than this are weekend placeholders

# ── Case type filters (substring match, lower-case) ───────────────────────────

LIS_PENDENS_KEYWORDS = [
    "mortgage foreclosure",
    "real property/mortgage",
    "real prop/mtge",
]

EVICTION_KEYWORDS = [
    "residential eviction",
    "unlawful detainer",
    "non-residential eviction",
]

JUDGMENT_KEYWORDS = [
    "enforce order/judgment",
    "enforce lien",
]

PROBATE_WANT = [
    "summary administration",
    "formal administration",
    "disposition w/o administration",
    "disposition without administration",
]

PROBATE_SKIP = [
    "guardian",
    "risk protection",
    "wills on deposit",
    "minor settlement",
    "name change",
    "dissolution",
    "paternity",
    "support",
    "injunction",
    "notice of trust",
    "incapacity",
    "developmentally disabled",
    "pre - need",
]

# ── Sheet headers (must match what run_all.py COL_MAPS expects) ───────────────
SHEET_HEADERS = {
    "lis_pendens": [
        "Location", "Event Type", "Case #", "Style", "Case Type",
        "Case Subtype", "Entered By", "Event Status", "Event Status Date",
        "Date/Time Entered", "Judicial Officer",
    ],
    "evictions": [
        "Location", "Event Type", "Case #", "Style", "Case Type",
        "Case Subtype", "Entered By", "Event Status", "Event Status Date",
        "Date/Time Entered", "Judicial Officer",
    ],
    "judgments": [
        "Instrument", "Property Owner", "Judgment Creditor", "Doc Type",
        "Book", "Page", "Date Filed",
    ],
    "probate": [
        "Case Category", "Case Type", "Case Number", "Title", "Case Create Date",
        "Decedent's First Name", "Decedent's Middle Name", "Decedent's Last Name",
        "Date of Death", "Rep or Petitioner First Name",
        "Rep or Petitioner Middle Name", "Rep or Petitioner Last Name",
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_csv(url):
    """Download a CSV and return list of row dicts. Returns [] on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        content = r.content.decode("utf-8", errors="replace")
        if len(content) < MIN_FILE_BYTES:
            return []
        reader = csv.DictReader(io.StringIO(content), delimiter="\t")
        return list(reader)
    except Exception as e:
        print(f"    fetch failed: {e}")
        return []


def clean_name(first, middle, last):
    parts = [p.strip() for p in [first, middle, last] if p and p.strip()]
    return " ".join(parts)


def normalize_date(raw):
    """Convert any date string to YYYY-MM-DD. Returns empty string on failure."""
    if not raw or not str(raw).strip():
        return ""
    raw = str(raw).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def group_by_case(rows):
    cases = {}
    for row in rows:
        cn = row.get("CaseNumber", "").strip()
        if cn:
            cases.setdefault(cn, []).append(row)
    return cases


def get_party(rows, *party_types):
    types_lower = [t.lower() for t in party_types]
    for row in rows:
        if row.get("PartyType", "").strip().lower() in types_lower:
            return row
    return None


def is_junk_party(name):
    n = (name or "").upper().strip()
    junk = [
        "UNKNOWN TENANT", "UNKNOWN SPOUSE", "UNKNOWN PARTIES",
        "JOHN DOE", "JANE DOE", "UNKNOWN HEIRS", "UNKNOWN OCCUPANTS",
        "HILLSBOROUGH COUNTY", "CITY OF TAMPA", "STATE OF FLORIDA",
        "UNITED STATES",
    ]
    return not n or any(j in n for j in junk)


# ── Sheet helpers ─────────────────────────────────────────────────────────────

def get_existing_cases(sheet_id, tab_name):
    try:
        rows = sheets_helper.read_all_rows(sheet_id, tab_name)
        if not rows or len(rows) < 2:
            return set()
        headers = rows[0]
        case_col = None
        for name in ["Case #", "Case Number", "Instrument"]:
            if name in headers:
                case_col = headers.index(name)
                break
        if case_col is None:
            return set()
        return {row[case_col].strip() for row in rows[1:] if len(row) > case_col and row[case_col].strip()}
    except Exception:
        return set()


def tab_has_headers(sheet_id, tab_name):
    try:
        rows = sheets_helper.read_all_rows(sheet_id, tab_name)
        return bool(rows and rows[0])
    except Exception:
        return False


def write_rows(sheet_id, tab_name, sig_key, data_rows):
    if not data_rows:
        return 0
    try:
        if not tab_has_headers(sheet_id, tab_name):
            header = SHEET_HEADERS.get(sig_key, [])
            sheets_helper.append_rows(sheet_id, tab_name, [header] + data_rows)
        else:
            sheets_helper.append_rows(sheet_id, tab_name, data_rows)
        return len(data_rows)
    except Exception as e:
        print(f"    sheet write failed ({tab_name}): {e}")
        return 0


def get_dates_to_scrape(sheet_id, tab_name):
    today     = datetime.now().date()
    yesterday = today - timedelta(days=1)
    try:
        rows     = sheets_helper.read_all_rows(sheet_id, tab_name)
        has_data = len(rows) > 1
    except Exception:
        has_data = False

    if has_data:
        return [yesterday]

    dates, d = [], yesterday
    for _ in range(BACKFILL_DAYS):
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)
    return sorted(dates)


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_lis_pendens(rows, existing):
    new_rows = []
    for case_num, case_rows in group_by_case(rows).items():
        if case_num in existing:
            continue
        first = case_rows[0]
        ct    = first.get("CaseTypeDescription", "").strip()
        if not any(kw in ct.lower() for kw in LIS_PENDENS_KEYWORDS):
            continue

        filing_date = normalize_date(first.get("FilingDate", ""))

        owner_row = get_party(case_rows, "Defendant")
        if not owner_row:
            continue

        first_n = owner_row.get("FirstName", "").strip()
        middle  = owner_row.get("MiddleName", "").strip()
        last_n  = owner_row.get("LastName/CompanyName", "").strip()

        if is_junk_party(last_n):
            for r in case_rows:
                if r.get("PartyType", "").lower() == "defendant":
                    l = r.get("LastName/CompanyName", "").strip()
                    if not is_junk_party(l):
                        first_n, middle, last_n = r.get("FirstName","").strip(), r.get("MiddleName","").strip(), l
                        owner_row = r
                        break

        if not last_n or is_junk_party(last_n):
            continue

        owner_name    = clean_name(first_n, middle, last_n)
        plaintiff_row = get_party(case_rows, "Plaintiff")
        plaintiff     = ""
        if plaintiff_row:
            plaintiff = clean_name(
                plaintiff_row.get("FirstName","").strip(),
                plaintiff_row.get("MiddleName","").strip(),
                plaintiff_row.get("LastName/CompanyName","").strip(),
            )

        style = f"{plaintiff} Vs. {owner_name}" if plaintiff else owner_name

        new_rows.append([
            "Hillsborough", "Case", case_num, style, ct,
            "", "", "", "", filing_date, "",
        ])
        existing.add(case_num)
    return new_rows


def parse_evictions(rows, existing):
    new_rows = []
    for case_num, case_rows in group_by_case(rows).items():
        if case_num in existing:
            continue
        first = case_rows[0]
        ct    = first.get("CaseTypeDescription", "").strip()
        if not any(kw in ct.lower() for kw in EVICTION_KEYWORDS):
            continue

        filing_date   = normalize_date(first.get("FilingDate", ""))
        plaintiff_row = get_party(case_rows, "Plaintiff")
        if not plaintiff_row:
            continue

        plaintiff = clean_name(
            plaintiff_row.get("FirstName","").strip(),
            plaintiff_row.get("MiddleName","").strip(),
            plaintiff_row.get("LastName/CompanyName","").strip(),
        )

        def_row   = get_party(case_rows, "Defendant")
        defendant = ""
        if def_row:
            defendant = clean_name(
                def_row.get("FirstName","").strip(),
                def_row.get("MiddleName","").strip(),
                def_row.get("LastName/CompanyName","").strip(),
            )

        style = f"{plaintiff} Vs. {defendant}" if defendant else plaintiff

        new_rows.append([
            "Hillsborough", "Case", case_num, style, ct,
            "", "", "", "", filing_date, "",
        ])
        existing.add(case_num)
    return new_rows


def parse_judgments(rows, existing):
    new_rows = []
    for case_num, case_rows in group_by_case(rows).items():
        if case_num in existing:
            continue
        first = case_rows[0]
        ct    = first.get("CaseTypeDescription", "").strip()
        if not any(kw in ct.lower() for kw in JUDGMENT_KEYWORDS):
            continue

        filing_date = normalize_date(first.get("FilingDate", ""))
        def_row     = get_party(case_rows, "Defendant")
        if not def_row:
            continue

        dl = def_row.get("LastName/CompanyName", "").strip()
        if is_junk_party(dl):
            continue

        owner    = clean_name(def_row.get("FirstName","").strip(), def_row.get("MiddleName","").strip(), dl)
        pl_row   = get_party(case_rows, "Plaintiff")
        creditor = ""
        if pl_row:
            creditor = clean_name(
                pl_row.get("FirstName","").strip(),
                pl_row.get("MiddleName","").strip(),
                pl_row.get("LastName/CompanyName","").strip(),
            )

        new_rows.append([case_num, owner, creditor, ct, "", "", filing_date])
        existing.add(case_num)
    return new_rows


def parse_probate(rows, existing):
    new_rows = []
    for case_num, case_rows in group_by_case(rows).items():
        if case_num in existing:
            continue
        first = case_rows[0]
        ct    = first.get("CaseTypeDescription", "").strip()
        ct_lo = ct.lower()

        if not any(kw in ct_lo for kw in PROBATE_WANT):
            continue
        if any(kw in ct_lo for kw in PROBATE_SKIP):
            continue

        filing_date = normalize_date(first.get("FilingDate", ""))
        dec_row     = get_party(case_rows, "Decedent")
        if not dec_row:
            continue

        dec_first  = dec_row.get("FirstName", "").strip()
        dec_middle = dec_row.get("MiddleName", "").strip()
        dec_last   = dec_row.get("LastName/CompanyName", "").strip()
        if not dec_last:
            continue

        date_of_death = normalize_date(dec_row.get("DateofDeath", ""))

        pet_row    = get_party(case_rows, "Petitioner")
        pet_first  = pet_row.get("FirstName", "").strip() if pet_row else ""
        pet_middle = pet_row.get("MiddleName", "").strip() if pet_row else ""
        pet_last   = pet_row.get("LastName/CompanyName", "").strip() if pet_row else ""

        new_rows.append([
            "PR", ct, case_num,
            f"{dec_last}, {dec_first} - Estate",
            filing_date,
            dec_first, dec_middle, dec_last,
            date_of_death,
            pet_first, pet_middle, pet_last,
        ])
        existing.add(case_num)
    return new_rows


# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_hillsborough():
    """
    Scrape all signals for Hillsborough County and write to the Hillsborough sheet.
    Returns dict: {signal_key: count_new_records}
    """
    county_cfg = config.COUNTIES.get("hillsborough", {})
    if not county_cfg.get("active"):
        print("  Hillsborough not active — skipping")
        return {}

    sheet_id = county_cfg["sheet_id"]
    results  = {}

    print("\n── HILLSBOROUGH ──────────────────────────────")

    # ── Civil signals ──────────────────────────────────────────────────────────
    civil_signals = [
        ("lis_pendens", config.TABS["lis_pendens"], parse_lis_pendens),
        ("evictions",   config.TABS["evictions"],   parse_evictions),
        ("judgments",   config.TABS["judgments"],   parse_judgments),
    ]

    for sig_key, tab_name, parser_fn in civil_signals:
        dates    = get_dates_to_scrape(sheet_id, tab_name)
        existing = get_existing_cases(sheet_id, tab_name)
        total    = 0
        print(f"  {sig_key}: {len(dates)} date(s)")
        for d in dates:
            rows     = fetch_csv(CIVIL_URL.format(date=d.strftime("%Y%m%d")))
            new_rows = parser_fn(rows, existing) if rows else []
            written  = write_rows(sheet_id, tab_name, sig_key, new_rows)
            total   += written
            if written:
                print(f"    {d}: +{written}")
        results[sig_key] = total
        time.sleep(5)  # avoid Google Sheets rate limit
        print(f"  {tab_name}: {total} new")

    # ── Probate ────────────────────────────────────────────────────────────────
    tab_name = config.TABS["probate"]
    dates    = get_dates_to_scrape(sheet_id, tab_name)
    existing = get_existing_cases(sheet_id, tab_name)
    total    = 0
    print(f"  probate: {len(dates)} date(s)")
    for d in dates:
        rows     = fetch_csv(PROBATE_URL.format(date=d.strftime("%Y%m%d")))
        new_rows = parse_probate(rows, existing) if rows else []
        written  = write_rows(sheet_id, tab_name, "probate", new_rows)
        total   += written
        if written:
            print(f"    {d}: +{written}")
    results["probate"] = total
    print(f"  {tab_name}: {total} new")

    # ── Not yet available via free CSV ─────────────────────────────────────────
    results["mechanic_liens"] = 0
    results["tax_deeds"]      = 0
    results["surplus_funds"]  = 0

    return results
