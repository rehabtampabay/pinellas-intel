# ─────────────────────────────────────────────────────────────────────────────
# run_all.py  —  FL Property Intel  —  Main pipeline
#
# Execution order:
#   1. Scrape Pinellas (writes new records to Pinellas Google Sheet)
#   2. Scrape Hillsborough (writes new records to Hillsborough Google Sheet)
#   3. Load ALL historical records from ALL active county sheets
#   4. Build leads.json  →  GitHub Pages dashboard reads this file
#   5. Send summary email
# ─────────────────────────────────────────────────────────────────────────────

import json, os, sys, smtplib, re, time
from datetime import datetime
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import sheets_helper
from stacker import detect_stacks, get_stack_summary

# ── County scrapers ───────────────────────────────────────────────────────────
from scrapers.pinellas import (
    scrape_lis_pendens,
    scrape_probate,
    scrape_evictions,
    scrape_official_records_index,
    scrape_new_case_filings,
    scrape_surplus_funds,
)
from scrapers.hillsborough import scrape_hillsborough


# ─────────────────────────────────────────────────────────────────────────────
# Column maps — matched to ACTUAL sheet column names for each signal.
# The code tries each column name in order and uses the first with a value.
# These apply to ALL counties (both Pinellas and Hillsborough use same tab names).
# ─────────────────────────────────────────────────────────────────────────────

COL_MAPS = {
    "lis_pendens": {
        "name":      ["Style", "Name"],
        "case":      ["Case #", "Case Number", "Instrument"],
        # IMPORTANT: Pinellas sheet column is "Date/Time Entered" (with 'd').
        # Hillsborough scraper also writes to "Date/Time Entered".
        "date":      ["Date/Time Entered", "Date/Time Enter", "Event Status Date",
                      "Date Filed", "Filing Date"],
        "case_type": ["Case Type"],
        "address":   ["Address"],
        "amount":    ["Amount"],
        "name_type": "defendant",   # extract defendant from "BANK VS. OWNER"
    },
    "probate": {
        "name":      ["Title", "Owner / Party", "Style", "Name", "Decedent's Last Name"],
        "case":      ["Case Number", "Case #", "Instrument"],
        "date":      ["Case Create Date", "Date/Time Entered", "Date/Time Enter",
                      "Date Filed", "Filing Date"],
        "case_type": ["Case Type", "Doc Type", "Case Category"],
        "address":   ["Rep or Petitioner Attorney's Address", "Address"],
        "amount":    ["Amount"],
        "name_type": "raw",
    },
    "evictions": {
        "name":      ["Owner (Plaintiff)", "Style", "Name"],
        "case":      ["Case #", "Case Number"],
        "date":      ["Date/Time Entered", "Date/Time Enter", "Event Status Date",
                      "Date Filed"],
        "case_type": ["Case Type"],
        "address":   ["Address"],
        "amount":    ["Amount"],
        "name_type": "plaintiff",   # extract plaintiff from "LANDLORD VS. TENANT"
    },
    "mechanic_liens": {
        "name":      ["Property Owner", "Owner / Party", "Party Name", "Name"],
        "case":      ["Instrument", "Case #"],
        "date":      ["Date Filed", "Date/Time Entered", "Date/Time Enter"],
        "case_type": ["Doc Type", "Case Type"],
        "address":   ["Address"],
        "amount":    ["Amount"],
        "name_type": "raw",
        "filed_by_col": ["Lien Filer"],
    },
    "judgments": {
        "name":      ["Property Owner", "Owner / Party", "Party Name", "Style", "Name"],
        "case":      ["Instrument", "Case #", "Case Number"],
        "date":      ["Date Filed", "Date/Time Entered", "Date/Time Enter"],
        "case_type": ["Doc Type", "Case Type"],
        "address":   ["Address"],
        "amount":    ["Amount"],
        "name_type": "raw",
        "filed_by_col": ["Judgment Creditor"],
    },
    "tax_deeds": {
        "name":      ["Owner / Party", "Description", "Style", "name"],
        "case":      ["Instrument", "Case #", "Case Number"],
        "date":      ["Date Filed", "Date/Time Entered", "Date/Time Enter", "date_filed"],
        "case_type": ["Doc Type", "Case Type"],
        "address":   ["Address"],
        "amount":    ["Opening Bid", "Amount"],
        "name_type": "raw",
    },
    "surplus_funds": {
        "name":      ["Style", "Name", "Party Name", "Note"],
        "case":      ["Case #", "Case Number", "Source File"],
        "date":      ["Date/Time Entered", "Date/Time Enter", "Date Filed", "Date"],
        "case_type": ["Case Type", "Note"],
        "address":   ["Address"],
        "amount":    ["Amount", "Balance"],
        "name_type": "raw",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def get_col(rec, keys):
    """Return first non-empty value from rec matching any key in keys."""
    for k in keys:
        v = rec.get(k, "").strip()
        if v and v != "—":
            return v
    return "—"


def extract_defendant(style):
    """'BANK VS. HOMEOWNER' → returns (HOMEOWNER, BANK)"""
    if not style or " VS. " not in style.upper():
        return style, ""
    idx       = style.upper().find(" VS. ")
    plaintiff = style[:idx].strip()
    defendant = re.sub(r'\.?\s*et al\.?$', '', style[idx+5:], flags=re.IGNORECASE).strip()
    return defendant, plaintiff


def extract_plaintiff(style):
    """'LANDLORD VS. TENANT' → returns (LANDLORD, TENANT)"""
    if not style or " VS. " not in style.upper():
        return style, ""
    idx       = style.upper().find(" VS. ")
    plaintiff = style[:idx].strip()
    defendant = re.sub(r'\.?\s*et al\.?$', '', style[idx+5:], flags=re.IGNORECASE).strip()
    return plaintiff, defendant


def classify_case_type(case_type_str):
    """Map raw case type string to a clean category for dashboard filtering."""
    ct = (case_type_str or "").upper()
    if not ct or ct == "—":
        return "other"
    if any(x in ct for x in ["CONDO", "HOA", "HOMEOWNERS ASSOC",
                               "CONDOMINIUM", "ASSOCIATION"]):
        return "condo_hoa"
    if "NON-HOMESTEAD" in ct or "NON HOMESTEAD" in ct or "NONHOMESTEAD" in ct:
        return "non_homestead"
    if "HOMESTEAD" in ct:
        return "homestead"
    if "RESIDENTIAL EVICTION" in ct or "WRIT OF POSSESSION" in ct:
        return "residential"
    if "NON RESIDENTIAL" in ct or "COMMERCIAL" in ct or "BUSINESS" in ct:
        return "commercial"
    if any(x in ct for x in ["PROBATE", "ESTATE", "GUARDIAN", "TRUST",
                               "ADMINISTRATION"]):
        return "probate_estate"
    if any(x in ct for x in ["DISSOLUTION", "DIVORCE", "DOMESTIC"]):
        return "dissolution"
    return "other"


def score_lead(sig_key, case_type, name, date_str):
    """Calculate a lead score 0–100."""
    base  = config.SIGNAL_SCORES.get(sig_key, 10)
    score = base
    ct    = (case_type or "").upper()
    n     = (name or "").upper()
    cat   = classify_case_type(case_type)

    # Category bonuses
    if cat == "homestead":      score += 15
    if cat == "non_homestead":  score += 8
    if cat == "condo_hoa":      score += 5
    if cat == "dissolution":    score += 10
    if cat == "probate_estate": score += 12

    # Value tier bonuses
    if "RES3" in ct or "$250,000 OR MORE" in ct: score += 10
    if "RES2" in ct or "$50,001" in ct:           score += 5

    # Name flags
    # ESTATE OF bonus removed — name stripping now gives clean names, bonus was an artifact
    if "TRUST" in n and "BANK" not in n:          score += 3
    if "LLC" in n or " INC" in n:                 score -= 5

    # Recency bonus
    if date_str and date_str != "—":
        for fmt in ["%m/%d/%Y %H:%M", "%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"]:
            try:
                filed    = datetime.strptime(date_str[:16].strip(), fmt)
                days_ago = (datetime.today() - filed).days
                if days_ago <= 7:    score += 15
                elif days_ago <= 30: score += 8
                elif days_ago <= 90: score += 3
                break
            except Exception:
                continue

    return min(score, 100)


def safe(name, fn):
    """Run fn(), return result or 0 on exception."""
    try:
        r = fn()
        return r or 0
    except Exception as e:
        print(f"FAILED {name}: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Pinellas scraping
# ─────────────────────────────────────────────────────────────────────────────

def run_pinellas():
    print("\n── PINELLAS ──────────────────────────────────")
    results = {}
    results["lis_pendens"]   = safe("lis_pendens",  scrape_lis_pendens)
    results["probate"]       = safe("probate",       scrape_probate)
    results["evictions"]     = safe("evictions",     scrape_evictions)
    results["surplus_funds"] = safe("surplus",       scrape_surplus_funds)

    try:
        liens, judgments, tax_deeds = scrape_official_records_index()
        results["mechanic_liens"] = liens
        results["judgments"]      = judgments
        results["tax_deeds"]      = tax_deeds
    except Exception as e:
        print(f"Official Records failed: {e}")
        results["mechanic_liens"] = 0
        results["judgments"]      = 0
        results["tax_deeds"]      = 0

    try:
        jud_extra, tax_extra = scrape_new_case_filings()
        results["judgments"] = results.get("judgments", 0) + jud_extra
        results["tax_deeds"] = results.get("tax_deeds", 0) + tax_extra
    except Exception as e:
        print(f"New case filings failed: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Load all leads from all active county sheets
# ─────────────────────────────────────────────────────────────────────────────

def load_all_leads():
    """
    Read every active county's Google Sheet and build a unified list of leads.
    Pinellas and Hillsborough are kept cleanly separated by county tag.
    """
    all_leads = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    for county_key, county in config.COUNTIES.items():
        if not county["active"]:
            continue

        sheet_id    = county["sheet_id"]
        county_name = county["name"]
        print(f"\nLoading {county_name}...")

        for sig_key, tab_name in config.TABS.items():
            if sig_key == "dashboard":
                continue

            rows = sheets_helper.read_all_rows(sheet_id, tab_name)
            if not rows:
                continue

            headers   = rows[0]
            col_map   = COL_MAPS.get(sig_key, COL_MAPS["lis_pendens"])
            label     = config.SIGNAL_LABELS.get(sig_key, sig_key.upper())
            color     = config.SIGNAL_COLORS.get(sig_key, "#64748b")
            name_type = col_map.get("name_type", "raw")
            tab_count = 0

            for row in rows[1:]:
                rec = {headers[i]: row[i]
                       for i in range(min(len(headers), len(row)))}

                # Skip completely empty rows — check all possible ID columns
                case_check = (
                    rec.get("Case #", "").strip() or
                    rec.get("Case Number", "").strip() or
                    rec.get("Instrument", "").strip() or
                    rec.get("Style", "").strip() or
                    rec.get("Title", "").strip()
                )
                if not case_check:
                    continue

                # ── Probate: combine Decedent first+last, extract petitioner ──
                if sig_key == "probate":
                    first = pet_first = pet_middle = pet_last = ""
                    last  = ""
                    for k, v in rec.items():
                        ku = k.upper().strip()
                        vs = str(v).strip()
                        if "DECEDENT" in ku and "FIRST" in ku and "MIDDLE" not in ku:
                            first = vs
                        if "DECEDENT" in ku and "LAST" in ku and "MIDDLE" not in ku:
                            last = vs
                        if ("REP" in ku or "PETITIONER" in ku) and "FIRST" in ku and "MIDDLE" not in ku:
                            pet_first = vs
                        if ("REP" in ku or "PETITIONER" in ku) and "MIDDLE" in ku:
                            pet_middle = vs
                        if ("REP" in ku or "PETITIONER" in ku) and "LAST" in ku and "MIDDLE" not in ku:
                            pet_last = vs
                    if first or last:
                        raw_name = (first + " " + last).strip()
                    else:
                        raw_name = "—"
                        for v in rec.values():
                            v = str(v).strip()
                            if v and v != "—" and len(v) > 4:
                                if ("IN RE" in v.upper() or "ESTATE" in v.upper()
                                        or "MATTER OF" in v.upper()):
                                    raw_name = v
                                    break
                        if raw_name == "—":
                            raw_name = get_col(rec, col_map["name"])
                    petitioner_name = " ".join(
                        p for p in [pet_first, pet_middle, pet_last] if p
                    ).strip()
                else:
                    raw_name        = get_col(rec, col_map["name"])
                    petitioner_name = ""

                case_num  = get_col(rec, col_map["case"])
                date_val  = get_col(rec, col_map["date"])
                case_type = get_col(rec, col_map["case_type"])
                address   = get_col(rec, col_map["address"])
                amount    = get_col(rec, col_map.get("amount", ["Amount"]))
                filer_name = (get_col(rec, col_map.get("filed_by_col", []))
                              if col_map.get("filed_by_col") else "")

                # ── Name extraction ──
                if name_type == "defendant" and " VS. " in raw_name.upper():
                    display_name, filed_by = extract_defendant(raw_name)
                elif name_type == "plaintiff" and " VS. " in raw_name.upper():
                    display_name, filed_by = extract_plaintiff(raw_name)
                else:
                    display_name, filed_by = raw_name, ""

                # Strip probate prefix
                if sig_key == "probate" and display_name:
                    for prefix in ["IN RE: THE ESTATE OF ", "IN RE: ESTATE OF ",
                                   "IN RE: THE MATTER OF ", "IN RE: "]:
                        if display_name.upper().startswith(prefix):
                            display_name = display_name[len(prefix):].strip()
                            break

                # ── Normalize date to YYYY-MM-DD ──
                raw_date   = (date_val.split(" ")[0]
                              if date_val and date_val != "—" and " " in date_val
                              else date_val)
                clean_date = ""
                if raw_date and raw_date != "—":
                    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%Y/%m/%d"):
                        try:
                            clean_date = datetime.strptime(raw_date.strip(), fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue
                if not clean_date:
                    clean_date = "—"

                added_today = (clean_date == today_str)

                score = score_lead(sig_key, case_type, display_name, date_val)
                heat  = ("hot"  if score >= config.HOT_LEAD_THRESHOLD else
                         "warm" if score >= config.WARM_THRESHOLD else "cold")
                cat   = classify_case_type(case_type)

                if sig_key == "probate" and petitioner_name:
                    final_filed_by = petitioner_name[:60]
                elif sig_key in ("mechanic_liens", "judgments") and filer_name:
                    final_filed_by = filer_name[:60]
                else:
                    final_filed_by = filed_by[:60]

                all_leads.append({
                    "signal":        sig_key,
                    "label":         label,
                    "color":         color,
                    "name":          display_name[:80],
                    "filed_by":      final_filed_by,
                    "petitioner":    petitioner_name[:60] if sig_key == "probate" else "",
                    "case":          case_num[:40],
                    "address":       address[:80],
                    "date":          clean_date[:10],
                    "case_type":     case_type[:80],
                    "category":      cat,
                    "amount":        amount[:25],
                    "score":         score,
                    "heat":          heat,
                    "county":        county_name,
                    "added_today":   added_today,
                    "stacked":       False,
                    "stack_count":   1,
                    "stack_signals": [label],
                    "stack_label":   "",
                })
                tab_count += 1

            print(f"  {tab_name}: {tab_count} records")
            time.sleep(5)  # avoid Google Sheets API rate limit (60 reads/min)

    print("\nDetecting signal stacking...")
    all_leads = detect_stacks(all_leads)
    return all_leads


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard JSON builder
# ─────────────────────────────────────────────────────────────────────────────

def write_dashboard_json(county_results, total_new, all_leads):
    os.makedirs("data", exist_ok=True)
    all_leads.sort(key=lambda x: x["score"], reverse=True)

    hot     = sum(1 for l in all_leads if l["heat"] == "hot")
    stacked = sum(1 for l in all_leads if l.get("stacked"))
    stack_s = get_stack_summary(all_leads)

    by_county = {}
    for county_key, county in config.COUNTIES.items():
        if not county["active"]:
            continue
        name  = county["name"]
        leads = [l for l in all_leads if l["county"] == name]
        res   = county_results.get(county_key, {})
        by_county[name] = {
            "total":     len(leads),
            "new_today": sum(res.values()) if res else 0,
            "stacked":   sum(1 for l in leads if l.get("stacked")),
            "breakdown": {sig: len([l for l in leads if l["signal"] == sig])
                          for sig in config.SIGNAL_LABELS},
        }

    with open("data/leads.json", "w") as f:
        json.dump({
            "updated":       datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
            "total_new":     total_new,
            "total_records": len(all_leads),
            "hot_count":     hot,
            "stacked_count": stacked,
            "stack_summary": stack_s,
            "by_county":     by_county,
            "leads":         all_leads,
        }, f, indent=2)

    print(f"\nDashboard: {len(all_leads)} records | {hot} hot | "
          f"{stacked} stacked | {total_new} new today")


# ─────────────────────────────────────────────────────────────────────────────
# Email summary
# ─────────────────────────────────────────────────────────────────────────────

def send_email(county_results, total_new, elapsed, total_records, hot_count, stacked_count):
    if not config.EMAIL_PASSWORD:
        return

    lines = [
        "FL Property Intel — " + datetime.now().strftime("%Y-%m-%d"), "",
        "New leads added:      " + str(total_new),
        "Total on file:        " + str(total_records),
        "Hot leads (60+):      " + str(hot_count),
        "Stacked leads:        " + str(stacked_count) + "  ← same owner, multiple signals",
        "Runtime:              " + str(elapsed) + "s", "",
    ]

    for county_key, results in county_results.items():
        county_name = config.COUNTIES[county_key]["name"]
        lines.append(f"── {county_name} ──")
        for sig, count in results.items():
            lines.append("  " + config.SIGNAL_LABELS.get(sig, sig).ljust(15) + str(count))
        lines.append("")

    lines.append("Dashboard: https://rehabtampabay.github.io/pinellas-intel")

    try:
        msg = EmailMessage()
        msg.set_content("\n".join(lines))
        msg["Subject"] = (f"FL Intel — {total_new} new | {hot_count} hot | "
                          f"{stacked_count} stacked | {total_records} on file")
        msg["From"] = config.ALERT_EMAIL
        msg["To"]   = config.ALERT_EMAIL
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(config.ALERT_EMAIL, config.EMAIL_PASSWORD)
            s.send_message(msg)
        print("Email sent")
    except Exception as e:
        print(f"Email failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    start = datetime.now()
    print("=" * 50)
    print("FL PROPERTY INTEL — " + start.strftime("%Y-%m-%d %H:%M"))
    print("=" * 50)

    county_results = {}

    # ── Pinellas ───────────────────────────────────────────────────────────────
    if config.COUNTIES["pinellas"]["active"]:
        county_results["pinellas"] = run_pinellas()

    # ── Hillsborough ───────────────────────────────────────────────────────────
    if config.COUNTIES["hillsborough"]["active"]:
        county_results["hillsborough"] = scrape_hillsborough()

    # ── Build dashboard ────────────────────────────────────────────────────────
    total_new = sum(sum(r.values()) for r in county_results.values())

    print("\nLoading all historical records...")
    all_leads = load_all_leads()

    elapsed       = (datetime.now() - start).seconds
    hot_count     = sum(1 for l in all_leads if l["heat"] == "hot")
    stacked_count = sum(1 for l in all_leads if l.get("stacked"))

    write_dashboard_json(county_results, total_new, all_leads)
    send_email(county_results, total_new, elapsed,
               len(all_leads), hot_count, stacked_count)

    print("=" * 50)
    print(f"DONE — {total_new} new | {len(all_leads)} total | "
          f"{hot_count} hot | {stacked_count} stacked | {elapsed}s")
    print("=" * 50)


main()
