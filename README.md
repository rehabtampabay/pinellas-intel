# 🏠 Pinellas Intel — Property Intelligence System

Automated motivated seller lead engine for Pinellas County, FL.
Scrapes public county records daily, scores leads, and pushes to GoHighLevel CRM.

## Signals Tracked
- 🔴 Lis Pendens (Pre-Foreclosure)
- 🟣 Probate / Estate Filings
- 🟡 Evictions (Writ of Possession)
- 🟠 Mechanic Liens
- 🟢 Tax Deeds + Surplus Funds
- 🔵 Judgments

## Setup (One-Time)

### 1. Add GitHub Secrets
Go to your repo → Settings → Secrets and variables → Actions → New repository secret

Add these 3 secrets:

| Secret Name | Value |
|---|---|
| `GHL_API_KEY` | Your GoHighLevel API key |
| `EMAIL_PASSWORD` | Your Gmail app password |
| `GOOGLE_CREDENTIALS` | Your entire google_credentials.json file contents |

### 2. Enable GitHub Pages
Repo → Settings → Pages → Source: Deploy from branch → Branch: main → Folder: / (root)

### 3. Enable GitHub Actions
Repo → Actions tab → Enable workflows

### 4. Run Manually First
Actions tab → "Pinellas Intel — Daily Scrape" → Run workflow

---
Built for FL Acquisitions & Holdings LLC
