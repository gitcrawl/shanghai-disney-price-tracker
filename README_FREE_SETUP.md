# Shanghai Disneyland Price Tracker — Free Setup (GitHub Actions)

This is a **free** way to monitor Klook + Trip.com for Shanghai Disneyland tickets and email you when a **new all‑time low** appears for your dates.

## What you get
- Daily run at **07:00 Australia/Melbourne** (21:00 UTC).
- Checks dates: **2025‑09‑01** and **2025‑09‑02**.
- Uses **Playwright** to render dynamic pages, then finds the **lowest-looking price** via regex.
- Persists state in `data/history.json` (committed back to the repo).
- Sends **email alerts** (SMTP) for new all‑time lows + a daily snapshot.

## Quick start
1. Create a new **GitHub repo** and upload this folder.
2. In your repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `DATES` = `2025-09-01,2025-09-02`
   - `KLOOK_URL` = `https://YOUR-KLOOK-URL?date={DATE}`
   - `TRIPCOM_URL` = `https://YOUR-TRIPCOM-URL?date={DATE}`
   - `EMAIL_TO` = `you@example.com`
   - `EMAIL_FROM` = `alerts@example.com`
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` (from your mail provider)
3. Push to GitHub.
4. Open **Actions** tab → run **Workflow dispatch** once to test. It will also run daily at 07:00 Melbourne time.

> **Tip:** Many vendors render prices via JavaScript and sometimes vary content by region/headers. This Playwright workflow waits for the page to go **network idle** and then parses HTML as a robust fallback. If you can share exact URLs, you can tighten extraction with CSS selectors instead of regex.

## Customising
- Change `DATES` secret to any comma‑separated list (ISO format).
- Want hourly checks? Fork the cron in the workflow file.
- Don’t want the daily snapshot? Comment out the second `send_email(...)` in `main.py`.

## Child ticket note
Shanghai Disney typically allows **under‑3s** to enter **free**, so for a 22‑month‑old the tracker effectively prices **2 adults**. Always check latest policy on the vendor page before purchase.

## Costs
- **GitHub Actions:** free minutes for public repos (and generous for private, within limits).
- **Email:** use your existing SMTP account. No third‑party paid tools required.
