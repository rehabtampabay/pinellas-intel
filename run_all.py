# ================================================================
# FL PROPERTY INTEL — MASTER RUNNER
# Runs all active county scrapers, writes leads.json for dashboard.
# Schedule: weekdays at 2pm EST (19:00 UTC)
# ================================================================

import json, os, sys, smtplib, random
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


def safe(name, fn):
    try:
        r = fn()
        return r or 0
    except Exception as e:
        print("FAILED " + name + ": " + str(e))
        return 0


def run_pinellas():
    print("\n── PINELLAS ──────────────────────────────")
    sheet_id = config.COUNTIES["pinellas"]["sheet_id"]
    results  = {}

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
    """
    Read every historical record from every active county sheet.
    Returns list of unified lead dicts for the dashboard.
    """
    all_leads = []

    for county_key, county in config.COUNTIES.items():
        if not county["active"]:
            continue

        print("\nLoading " + county["name"] + " records...")
        sheet_id = county["sheet_id"]

        for sig_key, tab_name in config.TABS.items():
            if sig_key == "dashboard":
                continue

            rows = sheets_helper.read_all_rows(sheet_id, tab_name)
            if not rows:
                continue

            headers = rows[0]
            label   = config.SIGNAL_LABELS.get(sig_key, sig_key.upper())
            color   = config.SIGNAL_COLORS.get(sig_key, "#64748b")
            base    = config.SIGNAL_SCORES.get(sig_key, 15)

            for row in rows[1:]:
                rec  = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                lead = normalize_lead(rec, sig_key, label, color, base, county["name"])
                all_leads.append(lead)

        print(county["name"] + ": " + str(len([l for l in all_leads if l["county"] == county["name"]])) + " total records")

    return all_leads


def normalize_lead(rec, sig_key, label, color, base_score, county_name):
    """Turn any sheet row into a clean unified lead dict."""
    name = (rec.get("Style") or rec.get("Name") or rec.get("Party Name") or
            rec.get("Grantor") or rec.get("name") or rec.get("Owner") or "—")

    case_num = (rec.get("Case #") or rec.get("Case Number") or
                rec.get("instrument") or rec.get("Instrument Number") or "—")

    address = (rec.get("Address") or rec.get("Property Address") or
               rec.get("address") or "—")

    date_filed = (rec.get("Date/Time Enter") or rec.get("Date Filed") or
                  rec.get("date_filed") or rec.get("Date Created") or
                  rec.get("Filing Date") or "—")

    case_type = (rec.get("Case Type") or rec.get("doc_type") or
                 rec.get("Document Type") or "")

    amount = (rec.get("Amount") or rec.get("Opening Bid") or
              rec.get("Surplus Balance") or "")

    score = min(base_score + random.randint(0, 18), 100)
    heat  = "hot" if score >= config.HOT_LEAD_THRESHOLD else \
            "warm" if score >= 40 else "cold"

    return {
        "signal":    sig_key,
        "label":     label,
        "color":     color,
        "name":      str(name)[:80],
        "case":      str(case_num)[:40],
        "address":   str(address)[:80],
        "date":      str(date_filed)[:25],
        "case_type": str(case_type)[:60],
        "amount":    str(amount)[:25],
        "score":     score,
        "heat":      heat,
        "county":    county_name,
    }


def write_dashboard_json(county_results, total_new, all_leads):
    os.makedirs("data", exist_ok=True)

    all_leads.sort(key=lambda x: x["score"], reverse=True)
    hot = sum(1 for l in all_leads if l["heat"] == "hot")

    # Per-county breakdown for dashboard
    by_county = {}
    for county_key, county in config.COUNTIES.items():
        if not county["active"]:
            continue
        name = county["name"]
        leads = [l for l in all_leads if l["county"] == name]
        by_county[name] = {
            "total": len(leads),
            "new_today": sum(county_results.get(county_key, {}).values()),
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


def send_email(county_results, total_new, elapsed, total_records):
    if not config.EMAIL_PASSWORD:
        return
    lines = [
        "FL Property Intel — " + datetime.now().strftime("%Y-%m-%d"),
        "",
        "New leads added:  " + str(total_new),
        "Total on file:    " + str(total_records),
        "Runtime:          " + str(elapsed) + "s",
        "",
    ]
    for county_key, results in county_results.items():
        county_name = config.COUNTIES[county_key]["name"]
        lines.append("── " + county_name + " ──")
        for sig, count in results.items():
            label = config.SIGNAL_LABELS.get(sig, sig)
            lines.append("  " + label.ljust(15) + str(count))
        lines.append("")

    lines.append("Dashboard: https://rehabtampabay.github.io/pinellas-intel")

    try:
        msg = EmailMessage()
        msg.set_content("\n".join(lines))
        msg["Subject"] = "FL Intel — " + str(total_new) + " new | " + str(total_records) + " on file"
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

    # Pinellas (active)
    if config.COUNTIES["pinellas"]["active"]:
        county_results["pinellas"] = run_pinellas()

    # Hillsborough — scraper coming next, sheet ready
    # if config.COUNTIES["hillsborough"]["active"]:
    #     county_results["hillsborough"] = run_hillsborough()

    total_new = sum(sum(r.values()) for r in county_results.values())

    print("\nReading all historical records...")
    all_leads = load_all_leads()

    elapsed = (datetime.now() - start).seconds
    write_dashboard_json(county_results, total_new, all_leads)
    send_email(county_results, total_new, elapsed, len(all_leads))

    print("=" * 50)
    print("DONE — " + str(total_new) + " new | " +
          str(len(all_leads)) + " total | " + str(elapsed) + "s")
    print("=" * 50)


main()
