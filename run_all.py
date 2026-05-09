import json
import os
import sys
import smtplib
import gspread
from datetime import datetime
from email.message import EmailMessage
from google.oauth2.service_account import Credentials

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from scrapers.pinellas import (
    scrape_lis_pendens,
    scrape_probate,
    scrape_evictions,
    scrape_official_records_index,
    scrape_tax_deeds_and_surplus,
)


def safe_run(name, fn):
    try:
        result = fn()
        return result or 0
    except Exception as e:
        print("FAILED " + name + ": " + str(e))
        return 0


def get_sheet_records(tab_name, max_rows=200):
    """Pull actual records from a Google Sheet tab."""
    try:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_CREDENTIALS_FILE,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        client = gspread.authorize(creds)
        sheet = client.open(config.SPREADSHEET_NAME).worksheet(tab_name)
        all_rows = sheet.get_all_values()
        if len(all_rows) < 2:
            return []
        headers = all_rows[0]
        records = []
        for row in all_rows[1:max_rows]:
            record = {}
            for i, h in enumerate(headers):
                record[h] = row[i] if i < len(row) else ""
            records.append(record)
        return records
    except Exception as e:
        print("Could not read " + tab_name + ": " + str(e))
        return []


def write_dashboard_json(results, total_new):
    """
    Writes leads.json with both summary counts AND actual lead records
    so the dashboard can display full details.
    """
    os.makedirs("data", exist_ok=True)

    # Pull actual records from each sheet tab
    lead_records = []

    signal_map = {
        "lis_pendens":    (config.SHEETS["lis_pendens"],    "LIS PENDENS",    "#ef4444", 80),
        "probate":        (config.SHEETS["probate"],        "PROBATE",        "#a78bfa", 80),
        "evictions":      (config.SHEETS["evictions"],      "EVICTION",       "#f59e0b", 80),
        "mechanic_liens": (config.SHEETS["mechanic_liens"], "MECH LIEN",      "#f97316", 80),
        "judgments":      (config.SHEETS["judgments"],      "JUDGMENT",       "#14b8a6", 80),
        "tax_deeds":      (config.SHEETS["tax_deeds"],      "TAX DEED",       "#22c55e", 80),
    }

    base_scores = {
        "lis_pendens": 40, "probate": 35, "tax_deeds": 35,
        "mechanic_liens": 20, "judgments": 20, "evictions": 15,
    }

    for sig_key, (tab, label, color, limit) in signal_map.items():
        records = get_sheet_records(tab, max_rows=limit)
        for rec in records:
            # Build a unified lead object from whatever columns exist
            lead = build_lead_object(rec, sig_key, label, color, base_scores[sig_key])
            lead_records.append(lead)

    # Sort by score descending
    lead_records.sort(key=lambda x: x.get("score", 0), reverse=True)

    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "county": "Pinellas",
        "total_new": total_new,
        "total_records": len(lead_records),
        "breakdown": {
            "lis_pendens":    results.get("lis_pendens", 0),
            "probate":        results.get("probate", 0),
            "evictions":      results.get("evictions", 0),
            "mechanic_liens": results.get("mechanic_liens", 0),
            "judgments":      results.get("judgments", 0),
            "tax_deeds":      results.get("tax_deeds", 0),
        },
        "leads": lead_records
    }

    with open("data/leads.json", "w") as f:
        json.dump(payload, f, indent=2)

    print("Dashboard JSON updated: " + str(len(lead_records)) + " records written")


def build_lead_object(rec, sig_key, label, color, base_score):
    """
    Normalizes a sheet row into a unified lead object.
    Handles different column names across sheet tabs.
    """
    import random

    # Try to extract name from various column names
    name = (
        rec.get("Style") or
        rec.get("Name") or
        rec.get("Party Name") or
        rec.get("Grantor") or
        rec.get("name") or
        rec.get("Owner") or
        "—"
    )

    # Case number
    case_num = (
        rec.get("Case #") or
        rec.get("Case Number") or
        rec.get("instrument") or
        rec.get("Instrument Number") or
        rec.get("Case") or
        "—"
    )

    # Address
    address = (
        rec.get("Address") or
        rec.get("Property Address") or
        rec.get("address") or
        "—"
    )

    # Date
    date_filed = (
        rec.get("Date/Time Enter") or
        rec.get("Date Filed") or
        rec.get("date_filed") or
        rec.get("Date Created") or
        rec.get("Filing Date") or
        "—"
    )

    # Case type / doc type
    case_type = (
        rec.get("Case Type") or
        rec.get("doc_type") or
        rec.get("Document Type") or
        rec.get("Style") or
        ""
    )

    # Amount
    amount = (
        rec.get("Amount") or
        rec.get("Opening Bid") or
        rec.get("Surplus Balance") or
        ""
    )

    # Score: base + small random variance for visual interest
    score = min(base_score + random.randint(0, 20), 100)
    heat = "hot" if score >= 60 else "warm" if score >= 40 else "cold"

    return {
        "signal":    sig_key,
        "label":     label,
        "color":     color,
        "name":      name[:60] if name else "—",
        "case":      case_num[:30] if case_num else "—",
        "address":   address[:60] if address else "—",
        "date":      date_filed[:20] if date_filed else "—",
        "case_type": case_type[:50] if case_type else "",
        "amount":    amount[:20] if amount else "",
        "score":     score,
        "heat":      heat,
        "county":    "Pinellas",
    }


def send_summary(results, total_new, elapsed):
    if not config.EMAIL_PASSWORD:
        return
    lines = [
        "Pinellas Intel - " + datetime.now().strftime("%Y-%m-%d") + " Run Summary",
        "",
        "Total new leads added today: " + str(total_new),
        "Runtime: " + str(elapsed) + "s",
        "",
        "  Lis Pendens:     " + str(results.get("lis_pendens", 0)),
        "  Probate:         " + str(results.get("probate", 0)),
        "  Evictions:       " + str(results.get("evictions", 0)),
        "  Mechanic Liens:  " + str(results.get("mechanic_liens", 0)),
        "  Judgments:       " + str(results.get("judgments", 0)),
        "  Tax Deeds:       " + str(results.get("tax_deeds", 0)),
        "",
        "View dashboard: https://rehabtampabay.github.io/pinellas-intel",
    ]
    try:
        msg = EmailMessage()
        msg.set_content("\n".join(lines))
        msg["Subject"] = "Pinellas Intel - " + str(total_new) + " new leads added today"
        msg["From"] = config.ALERT_EMAIL
        msg["To"] = config.ALERT_EMAIL
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(config.ALERT_EMAIL, config.EMAIL_PASSWORD)
            server.send_message(msg)
        print("Email sent to " + config.ALERT_EMAIL)
    except Exception as e:
        print("Email failed: " + str(e))


def main():
    start = datetime.now()
    print("=" * 50)
    print("PINELLAS INTEL - " + start.strftime("%Y-%m-%d %H:%M"))
    print("=" * 50)

    results = {}

    results["lis_pendens"] = safe_run("lis_pendens", scrape_lis_pendens)
    results["probate"]     = safe_run("probate",     scrape_probate)
    results["evictions"]   = safe_run("evictions",   scrape_evictions)

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

    td_extra = safe_run("tax_deeds_site", scrape_tax_deeds_and_surplus)
    results["tax_deeds"] = results.get("tax_deeds", 0) + td_extra

    total_new = sum(results.values())
    elapsed   = (datetime.now() - start).seconds

    # Always write dashboard even if 0 new leads today
    # so dashboard shows all historical records from sheets
    write_dashboard_json(results, total_new)
    send_summary(results, total_new, elapsed)

    print("=" * 50)
    print("DONE - " + str(total_new) + " new leads in " + str(elapsed) + "s")
    print("=" * 50)


main()
