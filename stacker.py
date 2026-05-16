"""
Signal Stacking Engine
Detects when the same property owner appears across multiple
signal types and boosts their score accordingly.

A homeowner with:
  - Lis Pendens + Probate = foreclosure on an estate (score +30)
  - Lis Pendens + Mechanic Lien = contractor dispute + mortgage default (score +20)
  - Eviction + Judgment = landlord being squeezed from both sides (score +20)
"""

import re


def normalize_name(name):
    """
    Strips noise to find the core owner name for matching.
    'JOHN A SMITH' == 'JOHN SMITH' == 'Smith, John A'
    """
    if not name or name == "—":
        return ""
    n = name.upper().strip()
    # Remove common suffixes and filler
    for remove in [" ET AL", ".ET AL", " JR", " SR", " II", " III",
                   " TRUSTEE", " TR", " LLC", " INC", " CORP",
                   " ESTATE OF", "ESTATE OF ", " TRUST"]:
        n = n.replace(remove, "")
    # Remove punctuation
    n = re.sub(r'[^A-Z0-9 ]', '', n)
    # Collapse spaces
    n = re.sub(r'\s+', ' ', n).strip()
    # Sort words so "JOHN SMITH" == "SMITH JOHN"
    words = sorted(n.split())
    return " ".join(words)


def detect_stacks(all_leads):
    """
    Groups leads by normalized owner name within the same county.
    When the same owner appears in multiple signal types:
      - Marks all their leads as stacked
      - Adds stack_count and stack_signals fields
      - Boosts score by 20 per additional signal (max +40)

    Returns updated leads list with stacking info added.
    """
    # Group by county + normalized name
    groups = {}
    for i, lead in enumerate(all_leads):
        name = lead.get("name", "") or lead.get("filed_by", "")
        norm = normalize_name(name)
        if not norm or len(norm) < 4:
            continue
        county = lead.get("county", "")
        key    = county + "|" + norm
        if key not in groups:
            groups[key] = []
        groups[key].append(i)

    # Find stacked leads (same name, different signals)
    stacked_count = 0
    for key, indices in groups.items():
        if len(indices) < 2:
            continue

        # Get unique signals for this owner
        signals  = list(set(all_leads[i]["signal"] for i in indices))
        sig_labels = list(set(all_leads[i]["label"] for i in indices))

        if len(signals) < 2:
            continue  # Same signal type repeated — not a stack

        # This owner has multiple different distress signals
        stack_count  = len(signals)
        score_boost  = min((stack_count - 1) * 20, 40)

        for i in indices:
            lead = all_leads[i]
            new_score = min(lead["score"] + score_boost, 100)
            new_heat  = "hot"  if new_score >= 60 else \
                        "warm" if new_score >= 40 else "cold"

            all_leads[i] = {
                **lead,
                "score":         new_score,
                "heat":          new_heat,
                "stacked":       True,
                "stack_count":   stack_count,
                "stack_signals": sig_labels,
                "stack_label":   "STACKED " + str(stack_count) + "x",
            }
            stacked_count += 1

    if stacked_count > 0:
        print("  Signal stacking: " + str(stacked_count) + " leads stacked across " +
              str(len([g for g in groups.values() if len(set(all_leads[i]["signal"] for i in g)) > 1])) +
              " owners")

    return all_leads


def get_stack_summary(all_leads):
    """Returns a summary dict of stacking stats for the dashboard."""
    stacked = [l for l in all_leads if l.get("stacked")]
    if not stacked:
        return {"total_stacked": 0, "stack_2x": 0, "stack_3x": 0}
    return {
        "total_stacked": len(stacked),
        "stack_2x": len([l for l in stacked if l.get("stack_count") == 2]),
        "stack_3x": len([l for l in stacked if l.get("stack_count", 0) >= 3]),
    }
