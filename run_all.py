import json, os, sys, smtplib, re
from datetime import datetime
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import sheets_helper
from scrapers.pinellas import (
    scrape_lis_pendens,
    scrape_probate,
    scrape_evictions,
    scrape_official_records_index,
    scrape_tax_deeds_and_surplus,
)

# ── Column name mappings (what your sheets actually use) ─────────
# Each tab may have different column names — map them here
COL_MAPS = {
    "lis_pendens": {
        "name":      ["Style", "Name", "Party Name"],
        "case":      ["Case #", "Case Number"],
        "date":      ["Date/Time Enter", "Date Filed", "Filing Date"],
        "case_type": ["Case Type", "Document Type"],
        "address":   ["Address", "Property Address"],
        "amount":    ["Amount"],
        "location":  ["Location"],
    },
    "probate": {
        "name":      ["Style", "Name", "Decedent"],
        "case":      ["Case #", "Case Number"],
        "date":      ["Date/Time Enter", "Date Filed", "Filing Date"],
        "case_type": ["Case Type"],
        "address":   ["Address"],
        "amount":    ["Amount"],
    },
    "evictions": {
        "name":      ["Style", "Name"],
        "case":      ["Case #", "Case Number"],
        "date":      ["Date/Time Enter", "Date Filed"],
        "case_type": ["Case Type"],
        "address":   ["Address"],
        "amount":    ["Amount"],
    },
    "mechanic_liens": {
        "name":      ["name", "Name", "Grantor"],
        "case":      ["instrument", "Instrument Number", "Case #"],
        "date":      ["date_filed", "Date Filed"],
        "case_type": ["doc_type", "Document Type"],
        "address":   ["address", "Address"],
        "amount":    ["Amount"],
    },
    "judgments": {
        "name":      ["name", "Name"],
        "case":      ["instrument", "Case #"],
        "date":      ["date_filed", "Date Filed"],
        "case_type": ["doc_type", "Case Type"],
        "address":   ["address"],
        "amount":    ["Amount"],
    },
    "tax_deeds": {
        "name":      ["name", "Name", "Owner"],
        "case":      ["Case Number", "instrument"],
        "date":      ["Date Created", "date_filed"],
        "case_type": ["Status", "doc_type"],
        "address":   ["address", "Address"],
        "amount":    ["Opening Bid", "Amount"],
    },
}


def get_col(rec, keys):
    """Try multiple column name variants, return first match."""
    for k in keys:
        v = rec.get(k, "").strip()
        if v and v != "—":
            return v
    return "—"


def extract_defendant(style):
    """Extract defendant name from 'BANK Vs. JOHN SMITH.et al'"""
    if not style:
        return style, ""
    idx = style.upper().find(" VS. ")
    if idx == -1:
        return style, ""
    plaintiff = style[:idx].strip()
    defendant = style[idx+5:].strip()
    defendant = re.sub(r'\.?et al\.?$', '', defendant, flags=re.IGNORECASE).strip()
    defendant = re.sub(r'\. et al\.?$', '', defendant, flags=re.IGNORECASE).strip()
    return defendant, plaintiff


def score_lead(sig_key, case_type, name, date_str):
    """
    Real scoring logic based on actual signal and case type.
    Returns 0-100.
    """
    base = config.SIGNAL_SCORES.get(sig_key, 10)
    score = base
    ct = (case_type or "").upper()

    # Case type bonuses
    if "HOMESTEAD" in ct:
        score += 15          # Owner-occupied = motivated seller
    if "RES3" in ct or "$250,000 OR MORE" in ct:
        score += 10          # High value = more equity
    if "RES2" in ct or "$50,001" in ct:
        score += 5
    if "NON-HOMESTEAD" in ct:
        score += 8           # Investment property = investor may want out
    if "ESTATE" in ct or "PROBATE" in ct:
        score += 12          # Estate = heirs want cash
    if "HOA" in ct or "CONDOMINIUM" in ct or "CONDO" in ct:
        score += 5           # HOA foreclosure = owner in trouble
    if "DISSOLUTION" in ct or "DIVORCE" in ct:
        score += 10          # Divorce = forced sale situation

    # Name-based flags
    n = (name or "").upper()
    if "TRUST" in n:
        score += 3           # Trust = estate planning, may need to sell
    if "LLC" in n or "INC" in n:
        score -= 5           # Corporate owner = less motivated typically
    if "ESTATE OF" in n:
        score += 10          # Estate = probate situation

    # Recency bonus
    if date_str and date_str != "—":
        try:
            for fmt in ["%m/%d/%Y %H:%M", "%Y-%m-%d", "%m/%d/%Y",
                        "%B %d, %Y", "%-m/%-d/%Y"]:
                try:
                    filed = datetime.strptime(date_str[:16].strip(), fmt)
                    days_ago = (datetime.today() - filed).days
                    if days_ago <= 7:
                        score += 15
                    elif days_ago <= 30:
                        score += 8
                    elif days_ago <= 90:
                        score += 3
                    break
                except Exception:
                    continue
        except Exception:
            pass

    return min(score, 100)


def safe(name, fn):
    try:
        r = fn()
        return r or 0
    except Exception as e:
        print("FAILED " + name + ": " + str(e))
        return 0


def run_pinellas():
    print("\n── PINELLAS ──────────────────────────────")
    results = {}
    results["lis_pendens"] = safe("lis_pendens", scrape_lis_pendens)
    results["probate"]     = safe("probate",     scrape_probate)
    results["evictions"]   = safe("evictions",   scrape_evictions)
    try:
        liens, judgments, tax_deeds = scrape_official_records_index()
        results["mechanic_liens"] = liens
        results["judgments"]      = judgments
        results["tax_deeds"]      = tax_deeds
    except Exception as e:
        print("Official Records failed: " + str(e))
        results["mechanic_liens"] = 0
        results["judgments"]      = 0
        results["tax_deeds"]      = 0
    results["tax_deeds"] = results.get("tax_deeds", 0) + safe(
        "tax_deeds_site", scrape_tax_deeds_and_surplus)
    return results


def load_all_leads():
    all_leads = []
    for county_key, county in config.COUNTIES.items():
        if not county["active"]:
            continue
        sheet_id = county["sheet_id"]
        county_name = county["name"]
        print("\nLoading " + county_name + "...")

        for sig_key, tab_name in config.TABS.items():
            if sig_key == "dashboard":
                continue
            rows = sheets_helper.read_all_rows(sheet_id, tab_name)
            if not rows:
                continue

            headers  = rows[0]
            col_map  = COL_MAPS.get(sig_key, COL_MAPS["lis_pendens"])
            label    = config.SIGNAL_LABELS.get(sig_key, sig_key.upper())
            color    = config.SIGNAL_COLORS.get(sig_key, "#64748b")
            count    = 0

            for row in rows[1:]:
                rec = {}
                for i, h in enumerate(headers):
                    rec[h] = row[i] if i < len(row) else ""

                # Extract fields using flexible column mapping
                raw_name  = get_col(rec, col_map["name"])
                case_num  = get_col(rec, col_map["case"])
                date_val  = get_col(rec, col_map["date"])
                case_type = get_col(rec, col_map["case_type"])
                address   = get_col(rec, col_map["address"])
                amount    = get_col(rec, col_map.get("amount", ["Amount"]))

                # Extract defendant for lis pendens / evictions
                if sig_key in ("lis_pendens", "evictions") and " VS. " in raw_name.upper():
                    defendant, plaintiff = extract_defendant(raw_name)
                    display_name = defendant
                    filed_by     = plaintiff
                else:
                    display_name = raw_name
                    filed_by     = ""

                # Clean date — keep only date portion
                clean_date = date_val
                if date_val and date_val != "—":
                    # "7/14/2025 11:08:" → "7/14/2025"
                    clean_date = date_val.split(" ")[0] if " " in date_val else date_val

                # Real scoring
                score = score_lead(sig_key, case_type, raw_name, date_val)
                heat  = "hot"  if score >= config.HOT_LEAD_THRESHOLD else \
                        "warm" if score >= 40 else "cold"

                all_leads.append({
                    "signal":    sig_key,
                    "label":     label,
                    "color":     color,
                    "name":      display_name[:80],
                    "filed_by":  filed_by[:60],
                    "case":      case_num[:40],
                    "address":   address[:80],
                    "date":      clean_date[:15],
                    "case_type": case_type[:80],
                    "amount":    amount[:25],
                    "score":     score,
                    "heat":      heat,
                    "county":    county_name,
                })
                count += 1

            print("  " + tab_name + ": " + str(count) + " records")

    return all_leads


def write_dashboard_json(county_results, total_new, all_leads):
    os.makedirs("data", exist_ok=True)
    all_leads.sort(key=lambda x: x["score"], reverse=True)
    hot = sum(1 for l in all_leads if l["heat"] == "hot")

    by_county = {}
    for county_key, county in config.COUNTIES.items():
        if not county["active"]:
            continue
        name   = county["name"]
        leads  = [l for l in all_leads if l["county"] == name]
        res    = county_results.get(county_key, {})
        by_county[name] = {
            "total":     len(leads),
            "new_today": sum(res.values()) if res else 0,
            "breakdown": {
                sig: len([l for l in leads if l["signal"] == sig])
                for sig in config.SIGNAL_LABELS
            }
        }

    payload = {
        "updated":       datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "total_new":     total_new,
        "total_records": len(all_leads),
        "hot_count":     hot,
        "by_county":     by_county,
        "leads":         all_leads,
    }

    with open("data/leads.json", "w") as f:
        json.dump(payload, f, indent=2)

    print("\nDashboard: " + str(len(all_leads)) + " records | " +
          str(hot) + " hot | " + str(total_new) + " new today")


def send_email(county_results, total_new, elapsed, total_records, hot_count):
    if not config.EMAIL_PASSWORD:
        return
    lines = [
        "FL Property Intel — " + datetime.now().strftime("%Y-%m-%d"),
        "",
        "New leads added:  " + str(total_new),
        "Total on file:    " + str(total_records),
        "Hot leads:        " + str(hot_count),
        "Runtime:          " + str(elapsed) + "s",
        "",
    ]
    for county_key, results in county_results.items():
        lines.append("── " + config.COUNTIES[county_key]["name"] + " ──")
        for sig, count in results.items():
            lines.append("  " + config.SIGNAL_LABELS.get(sig, sig).ljust(15) + str(count))
        lines.append("")
    lines.append("Dashboard: https://rehabtampabay.github.io/pinellas-intel")

    try:
        msg = EmailMessage()
        msg.set_content("\n".join(lines))
        msg["Subject"] = "FL Intel — " + str(total_new) + " new | " + \
                         str(hot_count) + " hot | " + str(total_records) + " on file"
        msg["From"] = config.ALERT_EMAIL
        msg["To"]   = config.ALERT_EMAIL
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(config.ALERT_EMAIL, config.EMAIL_PASSWORD)
            s.send_message(msg)
        print("Email sent")
    except Exception as e:
        print("Email failed: " + str(e))


def main():
    start = datetime.now()
    print("=" * 50)
    print("FL PROPERTY INTEL — " + start.strftime("%Y-%m-%d %H:%M"))
    print("=" * 50)

    county_results = {}
    if config.COUNTIES["pinellas"]["active"]:
        county_results["pinellas"] = run_pinellas()

    total_new = sum(sum(r.values()) for r in county_results.values())

    print("\nLoading all historical records from sheets...")
    all_leads = load_all_leads()

    elapsed   = (datetime.now() - start).seconds
    hot_count = sum(1 for l in all_leads if l["heat"] == "hot")

    write_dashboard_json(county_results, total_new, all_leads)
    send_email(county_results, total_new, elapsed, len(all_leads), hot_count)

    print("=" * 50)
    print("DONE — " + str(total_new) + " new | " +
          str(len(all_leads)) + " total | " +
          str(hot_count) + " hot | " + str(elapsed) + "s")
    print("=" * 50)


main()
