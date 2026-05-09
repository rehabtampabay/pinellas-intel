import json
import os
import sys
import smtplib
from datetime import datetime
from email.message import EmailMessage

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


def write_dashboard_json(results, total_new):
    os.makedirs("data", exist_ok=True)
    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "county": "Pinellas",
        "total_new": total_new,
        "breakdown": {
            "lis_pendens":    results.get("lis_pendens", 0),
            "probate":        results.get("probate", 0),
            "evictions":      results.get("evictions", 0),
            "mechanic_liens": results.get("mechanic_liens", 0),
            "judgments":      results.get("judgments", 0),
            "tax_deeds":      results.get("tax_deeds", 0),
        }
    }
    with open("data/leads.json", "w") as f:
        json.dump(payload, f, indent=2)
    print("Dashboard JSON updated: " + str(total_new) + " total leads")


def send_summary(results, total_new, elapsed):
    if not config.EMAIL_PASSWORD:
        print("EMAIL_PASSWORD not set, skipping email")
        return
    lines = [
        "Pinellas Intel - " + datetime.now().strftime("%Y-%m-%d") + " Run Summary",
        "",
        "Total new leads: " + str(total_new),
        "Runtime: " + str(elapsed) + "s",
        "",
        "  Lis Pendens:     " + str(results.get("lis_pendens", 0)),
        "  Probate:         " + str(results.get("probate", 0)),
        "  Evictions:       " + str(results.get("evictions", 0)),
        "  Mechanic Liens:  " + str(results.get("mechanic_liens", 0)),
        "  Judgments:       " + str(results.get("judgments", 0)),
        "  Tax Deeds:       " + str(results.get("tax_deeds", 0)),
    ]
    try:
        msg = EmailMessage()
        msg.set_content("\n".join(lines))
        msg["Subject"] = "Pinellas Intel - " + str(total_new) + " new leads today"
        msg["From"] = config.ALERT_EMAIL
        msg["To"] = config.ALERT_EMAIL
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(config.ALERT_EMAIL, config.EMAIL_PASSWORD)
            server.send_message(msg)
        print("Summary email sent to " + config.ALERT_EMAIL)
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

    write_dashboard_json(results, total_new)
    send_summary(results, total_new, elapsed)

    print("=" * 50)
    print("DONE - " + str(total_new) + " new leads in " + str(elapsed) + "s")
    print("=" * 50)


main()
