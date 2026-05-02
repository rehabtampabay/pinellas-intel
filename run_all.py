"""
Pinellas Intel — Master Runner v2
"""

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
    scrape_new_case_filings,
    scrape_tax_deeds_and_surplus,
)


def main():
    start = datetime.now()
    print(f"\n{'='*55}")
    print(f"  PINELLAS INTEL v2 — {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    results = {}

    # ── Simple scrapers ──
    results["lis_pendens"] = safe_run("lis_pendens",    scrape_lis_pendens)
    results["probate"]     = safe_run("probate",        scrape_probate)
    results["evictions"]   = safe_run("evictions",      scrape_evictions)

    # ── Official Records index (fills liens + judgments + tax deeds) ──
    try:
        liens, judgments, tax_deeds = scrape_official_records_index()
        results["mechanic_liens"] = liens
        results["judgments"]      = judgments
        results["tax_deeds"]      = tax_deeds
        print(f"\n  ✅ Official Records: {liens} liens | {judgments} judgments | {tax_deeds} tax deeds")
    except Exception as e:
        print(f"\n  ❌ Official Records index crashed: {e}")
        results["mechanic_liens"] = 0
        results["judgments"]      = 0
        results["tax_deeds"]      = 0

    # ── New civil case filings → adds to judgments tab ──
    new_cases = safe_run("new_cases", scrape_new_case_filings)
    results["judgments"] = results.get("judgments", 0) + new_cases

    # ── Tax deeds site ──
    td_extra = safe_run("tax_deeds_site", scrape_tax_deeds_and_surplus)
    results["tax_deeds"] = results.get("tax_deeds", 0) + td_extra

    total_new = sum(results.values())

    write_dashboard_json(results, total_new)
    send_summary(results, total_new, (datetime.now() - start).seconds)

    print(f"\n{'='*55}")
    print(f"  DONE — {total_new} new leads | {(datetime.now()-start).seconds}s")
    print(f"{'='*55}\n")


def safe_run(name, fn):
    try:
        result = fn()
        return result or 0
    except Exception as e:
        print(f"\n  ❌ {name} crashed: {e}")
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
    print(f"\n  💾 data/leads.json updated → {total_new} total")


def send_summary(results, total_new, elapsed):
    if not config.EMAIL_PASSWORD:
        print("  ⚠️  EMAIL_PASSWORD not set — skipping email")
        return

    lines = [
        f"Pinellas Intel — {datetime.now().strftime('%Y-%m-%d')} Run Summary\n",
        f"Total new leads: {total_new}",
        f"Runtime: {elapsed}s\n",
        f"  🏠 Lis Pendens (Pre-Foreclosure): {results.get('lis_pendens',0)} new records",
        f"  🟣 Probate / Estate:               {results.get('probate',0)} new records",
        f"  🚪 Evictions:                      {results.get('evictions',0)} new records",
        f"  🔧 Mechanic / HOA Liens:           {results.get('mechanic_liens',0)} new records",
        f"  ⚖️  Judgments:                      {results.get('judgments',0)} new records",
        f"  🏛️  Tax Deeds + Surplus:            {results.get('tax_deeds',0)} new records",
    ]

    try:
        msg = EmailMessage()
        msg.set_content("\n".join(lines))
        msg["Subject"] = f"✅ Pinellas Intel — {total_new} new leads today"
        msg["From"]    = config.ALERT_EMAIL
        msg["To"]      = config.ALERT_EMAIL

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(config.ALERT_EMAIL, config.EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"  📧 Summary emailed to {config.ALERT_EMAIL}")
    except Exception as e:
        print(f"  ⚠️  Email failed: {e}")


if __name__ == "__main__":
    main()"""
Pinellas Intel — Master Runner v2
"""

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
    scrape_new_case_filings,
    scrape_tax_deeds_and_surplus,
)


def main():
    start = datetime.now()
    print(f"\n{'='*55}")
    print(f"  PINELLAS INTEL v2 — {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    results = {}

    # ── Simple scrapers ──
    results["lis_pendens"] = safe_run("lis_pendens",    scrape_lis_pendens)
    results["probate"]     = safe_run("probate",        scrape_probate)
    results["evictions"]   = safe_run("evictions",      scrape_evictions)

    # ── Official Records index (fills liens + judgments + tax deeds) ──
    try:
        liens, judgments, tax_deeds = scrape_official_records_index()
        results["mechanic_liens"] = liens
        results["judgments"]      = judgments
        results["tax_deeds"]      = tax_deeds
        print(f"\n  ✅ Official Records: {liens} liens | {judgments} judgments | {tax_deeds} tax deeds")
    except Exception as e:
        print(f"\n  ❌ Official Records index crashed: {e}")
        results["mechanic_liens"] = 0
        results["judgments"]      = 0
        results["tax_deeds"]      = 0

    # ── New civil case filings → adds to judgments tab ──
    new_cases = safe_run("new_cases", scrape_new_case_filings)
    results["judgments"] = results.get("judgments", 0) + new_cases

    # ── Tax deeds site ──
    td_extra = safe_run("tax_deeds_site", scrape_tax_deeds_and_surplus)
    results["tax_deeds"] = results.get("tax_deeds", 0) + td_extra

    total_new = sum(results.values())

    write_dashboard_json(results, total_new)
    send_summary(results, total_new, (datetime.now() - start).seconds)

    print(f"\n{'='*55}")
    print(f"  DONE — {total_new} new leads | {(datetime.now()-start).seconds}s")
    print(f"{'='*55}\n")


def safe_run(name, fn):
    try:
        result = fn()
        return result or 0
    except Exception as e:
        print(f"\n  ❌ {name} crashed: {e}")
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
    print(f"\n  💾 data/leads.json updated → {total_new} total")


def send_summary(results, total_new, elapsed):
    if not config.EMAIL_PASSWORD:
        print("  ⚠️  EMAIL_PASSWORD not set — skipping email")
        return

    lines = [
        f"Pinellas Intel — {datetime.now().strftime('%Y-%m-%d')} Run Summary\n",
        f"Total new leads: {total_new}",
        f"Runtime: {elapsed}s\n",
        f"  🏠 Lis Pendens (Pre-Foreclosure): {results.get('lis_pendens',0)} new records",
        f"  🟣 Probate / Estate:               {results.get('probate',0)} new records",
        f"  🚪 Evictions:                      {results.get('evictions',0)} new records",
        f"  🔧 Mechanic / HOA Liens:           {results.get('mechanic_liens',0)} new records",
        f"  ⚖️  Judgments:                      {results.get('judgments',0)} new records",
        f"  🏛️  Tax Deeds + Surplus:            {results.get('tax_deeds',0)} new records",
    ]

    try:
        msg = EmailMessage()
        msg.set_content("\n".join(lines))
        msg["Subject"] = f"✅ Pinellas Intel — {total_new} new leads today"
        msg["From"]    = config.ALERT_EMAIL
        msg["To"]      = config.ALERT_EMAIL

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(config.ALERT_EMAIL, config.EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"  📧 Summary emailed to {config.ALERT_EMAIL}")
    except Exception as e:
        print(f"  ⚠️  Email failed: {e}")


if __name__ == "__main__":
    main()
