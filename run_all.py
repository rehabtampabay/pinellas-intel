"""
Pinellas Intel — Master Runner
Runs all scrapers, scores leads, pushes hot leads to GHL,
and writes data/leads.json for the dashboard.
"""

import json
import os
import sys
import smtplib
from datetime import datetime
from email.message import EmailMessage

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from scrapers.pinellas import (
    scrape_lis_pendens,
    scrape_probate,
    scrape_evictions,
    scrape_mechanic_liens,
    scrape_judgments,
    scrape_tax_deeds_and_surplus,
)

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    start = datetime.now()
    print(f"\n{'='*55}")
    print(f"  PINELLAS INTEL — {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    results = {}

    # Run all scrapers
    scrapers = [
        ("lis_pendens",     scrape_lis_pendens),
        ("probate",         scrape_probate),
        ("evictions",       scrape_evictions),
        ("mechanic_liens",  scrape_mechanic_liens),
        ("judgments",       scrape_judgments),
        ("tax_deeds",       scrape_tax_deeds_and_surplus),
    ]

    total_new = 0
    for key, fn in scrapers:
        try:
            count = fn()
            results[key] = count or 0
            total_new += results[key]
        except Exception as e:
            print(f"\n  ❌ {key} scraper crashed: {e}")
            results[key] = 0

    # Write dashboard JSON
    write_dashboard_json(results, total_new)

    # Send summary email
    elapsed = (datetime.now() - start).seconds
    send_summary(results, total_new, elapsed)

    print(f"\n{'='*55}")
    print(f"  DONE — {total_new} new leads | {elapsed}s")
    print(f"{'='*55}\n")


def write_dashboard_json(results, total_new):
    """Writes data/leads.json so the GitHub Pages dashboard can read it."""
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

    print(f"\n  💾 data/leads.json updated")


def send_summary(results, total_new, elapsed):
    """Emails a summary report."""
    if not config.EMAIL_PASSWORD:
        print("  ⚠️  EMAIL_PASSWORD not set — skipping email")
        return

    lines = [f"Pinellas Intel — {datetime.now().strftime('%Y-%m-%d')} Run Summary\n"]
    lines.append(f"Total new leads: {total_new}")
    lines.append(f"Runtime: {elapsed}s\n")

    signal_labels = {
        "lis_pendens":    "🏠 Lis Pendens (Pre-Foreclosure)",
        "probate":        "⚖️  Probate / Estate",
        "evictions":      "🚪 Evictions",
        "mechanic_liens": "🔧 Mechanic Liens",
        "judgments":      "⚖️  Judgments",
        "tax_deeds":      "🏛️  Tax Deeds + Surplus",
    }

    for key, label in signal_labels.items():
        count = results.get(key, 0)
        lines.append(f"  {label}: {count} new records")

    body = "\n".join(lines)

    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = f"✅ Pinellas Intel — {total_new} new leads today"
        msg["From"] = config.ALERT_EMAIL
        msg["To"] = config.ALERT_EMAIL

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(config.ALERT_EMAIL, config.EMAIL_PASSWORD)
            server.send_message(msg)

        print(f"  📧 Summary emailed to {config.ALERT_EMAIL}")
    except Exception as e:
        print(f"  ⚠️  Email failed: {e}")


if __name__ == "__main__":
    main()
