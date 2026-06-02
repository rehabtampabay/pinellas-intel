# ─────────────────────────────────────────────────────────────────────────────
# scrapers/hillsborough.py  —  Hillsborough County lead scraper
#
# Data source: publicrec.hillsclerk.com  (free, no auth required)
# NOTE: This site blocks GitHub Actions IPs. Run locally on your Mac.
#
# Civil file: comma-delimited CSV with UTF-8 BOM
#   CaseCategory,CaseTypeDescription,CaseNumber,Title,FilingDate,
#   PartyType,FirstName,MiddleName,LastName/CompanyName,PartyAddress,Attorney
#
# Probate file: same format with extra DateofDeath column
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

# ── URLs ──────────────────────────────────────────────────────────────────────
CIVIL_URL   = "https://publicrec.hillsclerk.com/Civil/dailyfilings/CivilFiling_{date}.csv"
PROBATE_URL = "https://publicrec.hillsclerk.com/Probate/dailyfilings/ProbateFiling_{date}.csv"
HEADERS     = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
BACKFILL_DAYS = 30
MIN_BYTES     = 300

# ── Case type filters ─────────────────────────────────────────────────────────
LIS_PENDENS_KW = ["mortgage foreclosure", "real property/mortgage", "real prop/mtge"]
EVICTION_KW    = ["residential eviction", "unlawful detainer", "non-residential eviction"]
JUDGMENT_KW    = ["enforce order/judgment", "enforce lien"]
PROBATE_WANT   = ["summary administration", "formal administration",
                  "disposition w/o administration", "disposition without administration"]
PROBATE_SKIP   = ["guardian", "risk protection", "wills on deposit", "minor settlement",
                  "name change", "dissolution", "paternity", "support", "injunction",
                  "notice of trust", "incapacity", "developmentally disabled", "pre - need"]

# ── Sheet headers — must match COL_MAPS in run_all.py ────────────────────────
SHEET_HEADERS = {
    "lis_pendens": ["Location", "Event Type", "Case #", "Style", "Case Type",
                    "Case Subtype", "Entered By", "Event Status", "Event Status Date",
                    "Date/Time Entered", "Judicial Officer"],
    "evictions":   ["Location", "Event Type", "Case #", "Style", "Case Type",
                    "Case Subtype", "Entered By", "Event Status", "Event Status Date",
                    "Date/Time Entered", "Judicial Officer"],
    "judgments":   ["Instrument", "Property Owner", "Judgment Creditor",
                    "Doc Type", "Book", "Page", "Date Filed"],
    "probate":     ["Case Category", "Case Type", "Case Number", "Title",
                    "Case Create Date", "Decedent's First Name", "Decedent's Middle Name",
                    "Decedent's Last Name", "Date of Death",
                    "Rep or Petitioner First Name", "Rep or Petitioner Middle Name",
                    "Rep or Petitioner Last Name"],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_csv(url):
    """Download CSV. Returns [] on failure or weekend placeholder."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        content = r.content.decode("utf-8", errors="replace")
        if len(content) < MIN_BYTES:
            return []
        # Strip UTF-8 BOM if present
        if content.startswith("\ufeff"):
            content = content[1:]
        reader = csv.DictReader(io.StringIO(content))
        return list(reader)
    except Exception:
        return []


def clean_name(*parts):
    return " ".join(p.strip() for p in parts if p and p.strip())


def normalize_date(raw):
    if not raw or not str(raw).strip():
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).strftime("%Y-%m-%d")
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


def get_party(rows, *types):
    types_lo = [t.lower() for t in types]
    for row in rows:
        if row.get("PartyType", "").strip().lower() in types_lo:
            return row
    return None


def is_junk(name):
    n = (name or "").upper()
    return not n or any(j in n for j in [
        "UNKNOWN TENANT", "UNKNOWN SPOUSE", "UNKNOWN PARTIES",
        "JOHN DOE", "JANE DOE", "UNKNOWN HEIRS", "HILLSBOROUGH COUNTY",
        "CITY OF TAMPA", "STATE OF FLORIDA", "UNITED STATES",
    ])


def get_existing_cases(sheet_id, tab_name):
    """Return set of case numbers already in the sheet."""
    try:
        time.sleep(2)
        rows = sheets_helper.read_all_rows(sheet_id, tab_name)
        if not rows or len(rows) < 2:
            return set()
        headers  = rows[0]
        case_col = None
        for name in ["Case #", "Case Number", "Instrument"]:
            if name in headers:
                case_col = headers.index(name)
                break
        if case_col is None:
            return set()
        return {r[case_col].strip() for r in rows[1:] if len(r) > case_col and r[case_col].strip()}
    except Exception:
        return set()


def get_dates_to_scrape(sheet_id, tab_name):
    """Empty tab → backfill 30 days. Has data → yesterday only."""
    today     = datetime.now().date()
    yesterday = today - timedelta(days=1)
    try:
        time.sleep(2)
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
    for cn, case_rows in group_by_case(rows).items():
        if cn in existing:
            continue
        first = case_rows[0]
        ct    = first.get("CaseTypeDescription", "").strip()
        if not any(kw in ct.lower() for kw in LIS_PENDENS_KW):
            continue
        filing_date = normalize_date(first.get("FilingDate", ""))
        owner_row   = get_party(case_rows, "Defendant")
        if not owner_row:
            continue
        last_n = owner_row.get("LastName/CompanyName", "").strip()
        if is_junk(last_n):
            continue
        owner     = clean_name(owner_row.get("FirstName",""), owner_row.get("MiddleName",""), last_n)
        pl_row    = get_party(case_rows, "Plaintiff")
        plaintiff = clean_name(pl_row.get("FirstName",""), pl_row.get("MiddleName",""),
                               pl_row.get("LastName/CompanyName","")) if pl_row else ""
        style = f"{plaintiff} Vs. {owner}" if plaintiff else owner
        new_rows.append(["Hillsborough","Case",cn,style,ct,"","","","",filing_date,""])
        existing.add(cn)
    return new_rows


def parse_evictions(rows, existing):
    new_rows = []
    for cn, case_rows in group_by_case(rows).items():
        if cn in existing:
            continue
        first = case_rows[0]
        ct    = first.get("CaseTypeDescription", "").strip()
        if not any(kw in ct.lower() for kw in EVICTION_KW):
            continue
        filing_date = normalize_date(first.get("FilingDate", ""))
        pl_row      = get_party(case_rows, "Plaintiff")
        if not pl_row:
            continue
        plaintiff = clean_name(pl_row.get("FirstName",""), pl_row.get("MiddleName",""),
                               pl_row.get("LastName/CompanyName",""))
        def_row   = get_party(case_rows, "Defendant")
        defendant = clean_name(def_row.get("FirstName",""), def_row.get("MiddleName",""),
                               def_row.get("LastName/CompanyName","")) if def_row else ""
        style = f"{plaintiff} Vs. {defendant}" if defendant else plaintiff
        new_rows.append(["Hillsborough","Case",cn,style,ct,"","","","",filing_date,""])
        existing.add(cn)
    return new_rows


def parse_judgments(rows, existing):
    new_rows = []
    for cn, case_rows in group_by_case(rows).items():
        if cn in existing:
            continue
        first = case_rows[0]
        ct    = first.get("CaseTypeDescription", "").strip()
        if not any(kw in ct.lower() for kw in JUDGMENT_KW):
            continue
        filing_date = normalize_date(first.get("FilingDate", ""))
        def_row     = get_party(case_rows, "Defendant")
        if not def_row:
            continue
        dl = def_row.get("LastName/CompanyName", "").strip()
        if is_junk(dl):
            continue
        owner    = clean_name(def_row.get("FirstName",""), def_row.get("MiddleName",""), dl)
        pl_row   = get_party(case_rows, "Plaintiff")
        creditor = clean_name(pl_row.get("FirstName",""), pl_row.get("MiddleName",""),
                              pl_row.get("LastName/CompanyName","")) if pl_row else ""
        new_rows.append([cn, owner, creditor, ct, "", "", filing_date])
        existing.add(cn)
    return new_rows


def parse_probate(rows, existing):
    new_rows = []
    for cn, case_rows in group_by_case(rows).items():
        if cn in existing:
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
        dec_last = dec_row.get("LastName/CompanyName", "").strip()
        if not dec_last:
            continue
        dec_first  = dec_row.get("FirstName", "").strip()
        dec_middle = dec_row.get("MiddleName", "").strip()
        dod        = normalize_date(dec_row.get("DateofDeath", ""))
        pet_row    = get_party(case_rows, "Petitioner")
        pet_first  = pet_row.get("FirstName","").strip()  if pet_row else ""
        pet_mid    = pet_row.get("MiddleName","").strip()  if pet_row else ""
        pet_last   = pet_row.get("LastName/CompanyName","").strip() if pet_row else ""
        new_rows.append(["PR", ct, cn, f"{dec_last}, {dec_first} - Estate",
                         filing_date, dec_first, dec_middle, dec_last,
                         dod, pet_first, pet_mid, pet_last])
        existing.add(cn)
    return new_rows


# ── Main ──────────────────────────────────────────────────────────────────────

def scrape_hillsborough():
    county_cfg = config.COUNTIES.get("hillsborough", {})
    if not county_cfg.get("active"):
        print("  Hillsborough not active — skipping")
        return {}

    sheet_id = county_cfg["sheet_id"]
    results  = {}

    print("\n── HILLSBOROUGH ──────────────────────────────")

    # ── Civil signals: collect ALL dates first, then ONE sheet write ───────────
    civil_signals = [
        ("lis_pendens", config.TABS["lis_pendens"], parse_lis_pendens),
        ("evictions",   config.TABS["evictions"],   parse_evictions),
        ("judgments",   config.TABS["judgments"],   parse_judgments),
    ]

    for sig_key, tab_name, parser_fn in civil_signals:
        dates    = get_dates_to_scrape(sheet_id, tab_name)
        existing = get_existing_cases(sheet_id, tab_name)
        all_new  = []

        print(f"  {sig_key}: {len(dates)} date(s)")

        for d in dates:
            rows    = fetch_csv(CIVIL_URL.format(date=d.strftime("%Y%m%d")))
            parsed  = parser_fn(rows, existing) if rows else []
            all_new.extend(parsed)

        # Ensure header row exists, then write data
        ensure_header(sheet_id, tab_name, sig_key)
        written = 0
        if all_new:
            header = SHEET_HEADERS[sig_key]
            try:
                time.sleep(3)
                written = sheets_helper.append_new_rows(
                    sheet_id, tab_name,
                    [header] + all_new,
                    dedup_col=3  # Case # is col 3 (1-indexed)
                )
            except Exception as e:
                print(f"    write failed ({tab_name}): {e}")

        results[sig_key] = written
        print(f"  {tab_name}: {written} new")
        time.sleep(5)

    # ── Probate ────────────────────────────────────────────────────────────────
    tab_name = config.TABS["probate"]
    dates    = get_dates_to_scrape(sheet_id, tab_name)
    existing = get_existing_cases(sheet_id, tab_name)
    all_new  = []

    print(f"  probate: {len(dates)} date(s)")

    for d in dates:
        rows   = fetch_csv(PROBATE_URL.format(date=d.strftime("%Y%m%d")))
        parsed = parse_probate(rows, existing) if rows else []
        all_new.extend(parsed)

    ensure_header(sheet_id, tab_name, "probate")
    written = 0
    if all_new:
        header = SHEET_HEADERS["probate"]
        try:
            time.sleep(3)
            written = sheets_helper.append_new_rows(
                sheet_id, tab_name,
                [header] + all_new,
                dedup_col=3  # Case Number is col 3
            )
        except Exception as e:
            print(f"    write failed ({tab_name}): {e}")

    results["probate"] = written
    print(f"  {tab_name}: {written} new")

    results["mechanic_liens"] = 0
    results["tax_deeds"]      = 0
    results["surplus_funds"]  = 0

    return results


def ensure_header(sheet_id, tab_name, sig_key):
    """Write header row if the tab is empty or has NO_HEADER columns."""
    try:
        time.sleep(2)
        rows = sheets_helper.read_all_rows(sheet_id, tab_name)
        header = SHEET_HEADERS.get(sig_key, [])
        if not rows or not rows[0] or rows[0][0].startswith("NO_HEADER") or rows[0][0] == "":
            ws = sheets_helper.open_sheet(sheet_id, tab_name)
            ws.insert_row(header, index=1)
            print(f"    wrote header to {tab_name}")
    except Exception as e:
        print(f"    header check failed ({tab_name}): {e}")
