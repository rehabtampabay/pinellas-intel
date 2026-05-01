"""
Lead Scoring Engine
Scores each lead 0–100 based on signal type, stacking, recency, and amount.
"""

import config
from datetime import datetime


def score_lead(signal_type, amount=None, date_filed=None, additional_signals=None):
    """
    Returns an integer score 0–100.
    
    signal_type: one of the keys in config.SIGNAL_SCORES
    amount: dollar amount (for liens, judgments) — higher = more distress
    date_filed: date string — more recent = higher score
    additional_signals: list of other signals on same owner = stacking bonus
    """
    score = 0

    # Base score from signal type
    base = config.SIGNAL_SCORES.get(signal_type, 10)
    score += base

    # Recency bonus (filed in last 30 days = max bonus)
    if date_filed:
        try:
            filed = parse_date(date_filed)
            days_ago = (datetime.today() - filed).days
            if days_ago <= 7:
                score += 20
            elif days_ago <= 30:
                score += 10
            elif days_ago <= 90:
                score += 5
        except Exception:
            pass

    # Amount bonus (higher dollar amount = more desperate)
    if amount:
        try:
            amt = float(str(amount).replace("$", "").replace(",", "").strip())
            if amt > 100000:
                score += 15
            elif amt > 50000:
                score += 10
            elif amt > 10000:
                score += 5
        except Exception:
            pass

    # Stacking bonus (multiple signals on same owner = very motivated)
    if additional_signals:
        score += min(len(additional_signals) * 10, 20)  # max +20

    return min(score, 100)


def score_label(score):
    if score >= config.HOT_LEAD_THRESHOLD:
        return "🔥 HOT"
    elif score >= 40:
        return "⚡ WARM"
    else:
        return "❄️ COLD"


def parse_date(date_str):
    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%m-%d-%Y"]:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except Exception:
            continue
    return datetime.today()


def score_rows(rows, signal_type, date_col=None, amount_col=None):
    """
    Takes a list of rows (with header as first row),
    appends Score and Label columns, returns updated rows.
    """
    if not rows or len(rows) < 2:
        return rows

    header = rows[0] + ["Score", "Signal", "Heat"]
    scored = [header]

    for row in rows[1:]:
        date_val = row[date_col] if date_col and len(row) > date_col else None
        amount_val = row[amount_col] if amount_col and len(row) > amount_col else None

        s = score_lead(signal_type, amount=amount_val, date_filed=date_val)
        label = score_label(s)
        scored.append(row + [str(s), signal_type, label])

    return scored
