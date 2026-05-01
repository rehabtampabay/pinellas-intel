"""
GoHighLevel CRM Pusher
Sends new hot leads to GHL as contacts with proper tags.
"""

import requests
import config

GHL_HEADERS = {
    "Authorization": f"Bearer {config.GHL_API_KEY}",
    "Content-Type": "application/json",
    "Version": "2021-04-15"
}


def push_contact(lead: dict) -> bool:
    """
    Push a single lead to GoHighLevel.
    
    lead dict keys:
        first_name, last_name, address, city, state, zip,
        signal_type, county, score, case_number, date_filed, amount
    """
    if not config.GHL_API_KEY:
        print("  ⚠️  GHL_API_KEY not set — skipping CRM push")
        return False

    signal = lead.get("signal_type", "unknown")
    county = lead.get("county", "pinellas")
    score = lead.get("score", 0)
    heat = "hot" if score >= config.HOT_LEAD_THRESHOLD else "warm"

    tags = [
        f"county:{county}",
        f"signal:{signal.replace('_', '-')}",
        f"score:{heat}",
        "motivated-seller",
        "fl-intel",
        "auto-scraped"
    ]

    payload = {
        "firstName": lead.get("first_name", "Unknown"),
        "lastName": lead.get("last_name", "Owner"),
        "name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
        "address1": lead.get("address", ""),
        "city": lead.get("city", ""),
        "state": lead.get("state", "FL"),
        "postalCode": lead.get("zip", ""),
        "tags": tags,
        "source": "Pinellas Intel — Auto Scrape",
        "customField": [
            {"key": "signal_type", "field_value": signal},
            {"key": "county", "field_value": county},
            {"key": "lead_score", "field_value": str(score)},
            {"key": "case_number", "field_value": lead.get("case_number", "")},
            {"key": "date_filed", "field_value": lead.get("date_filed", "")},
            {"key": "amount", "field_value": lead.get("amount", "")},
        ]
    }

    try:
        resp = requests.post(
            f"{config.GHL_BASE_URL}/contacts/",
            json=payload,
            headers=GHL_HEADERS,
            timeout=15
        )
        if resp.status_code in [200, 201]:
            print(f"  ✅ GHL: {payload['name']} | {signal} | Score {score}")
            return True
        else:
            print(f"  ⚠️  GHL response {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ GHL push failed: {e}")
        return False


def push_hot_leads_from_sheet(tab_name, name_col=0, address_col=3,
                               signal_type="unknown", county="pinellas",
                               score_col=None, case_col=2, date_col=1):
    """
    Reads the sheet, finds hot leads (score >= threshold), pushes to GHL.
    Returns count pushed.
    """
    import sheets_helper

    try:
        sheet = sheets_helper.get_sheet(tab_name)
        all_rows = sheet.get_all_values()
    except Exception as e:
        print(f"  ❌ Could not read sheet {tab_name}: {e}")
        return 0

    if len(all_rows) < 2:
        return 0

    pushed = 0
    for row in all_rows[1:]:
        score = 0
        if score_col and len(row) > score_col:
            try:
                score = int(row[score_col])
            except Exception:
                pass

        if score < config.HOT_LEAD_THRESHOLD:
            continue

        name_parts = row[name_col].split(" ") if len(row) > name_col else ["Unknown"]
        first = name_parts[0] if name_parts else "Unknown"
        last = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Owner"

        lead = {
            "first_name": first,
            "last_name": last,
            "address": row[address_col] if len(row) > address_col else "",
            "city": "Pinellas",
            "state": "FL",
            "signal_type": signal_type,
            "county": county,
            "score": score,
            "case_number": row[case_col] if len(row) > case_col else "",
            "date_filed": row[date_col] if len(row) > date_col else "",
        }

        if push_contact(lead):
            pushed += 1

    return pushed
