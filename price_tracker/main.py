import os
import re
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# -------- CONFIG VIA ENV --------
DATES = os.getenv("DATES", "2025-09-01,2025-09-02").split(",")
KLOOK_URL = os.getenv("KLOOK_URL", "https://REPLACE-KLOOK-URL?date={DATE}")
TRIPCOM_URL = os.getenv("TRIPCOM_URL", "https://REPLACE-TRIPCOM-URL?date={DATE}")
EMAIL_TO = os.getenv("EMAIL_TO", "you@example.com")
EMAIL_FROM = os.getenv("EMAIL_FROM", "alerts@example.com")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.example.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
PEOPLE_SUMMARY = os.getenv("PEOPLE_SUMMARY", "2 adults + child (22 months; check policy)")
HISTORY_PATH = Path(os.getenv("HISTORY_PATH", "data/history.json"))

# Simple numeric fallback regex (currency symbols not strictly required)
PRICE_RE = re.compile(r"(?:A\$|AU\$|\$|¥|CNY)?\s?([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)")

async def fetch_min_price(page, url: str) -> float | None:
    try:
        await page.goto(url, wait_until="networkidle", timeout=45000)
        html = await page.content()
        prices = []
        for m in PRICE_RE.finditer(html):
            try:
                val = float(m.group(1).replace(",", ""))
                prices.append(val)
            except:
                pass
        return min(prices) if prices else None
    except Exception as e:
        print(f"[WARN] Failed to fetch {url}: {e}")
        return None

async def main():
    targets = []
    for d in [x.strip() for x in DATES if x.strip()]:
        targets.append(("KLOOK", d, KLOOK_URL.format(DATE=d)))
        targets.append(("TRIPCOM", d, TRIPCOM_URL.format(DATE=d)))

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for vendor, date_str, url in targets:
            price = await fetch_min_price(page, url)
            print(f"{vendor} {date_str} -> {price} ({url})")
            results.append({"vendor": vendor, "date": date_str, "url": url, "minPrice": price})
        await browser.close()

    # Determine cheapest across all vendors/dates
    cheapest = None
    for r in results:
        p = r["minPrice"]
        if p is not None and (cheapest is None or p < cheapest["price"]):
            cheapest = {"price": p, "vendor": r["vendor"], "date": r["date"], "url": r["url"]}

    # Load last best from history
    last_best = None
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            last_best = data.get("best")
        except Exception as e:
            print(f"[WARN] Failed reading history: {e}")

    should_alert = False
    if cheapest and cheapest["price"] is not None:
        if not last_best or cheapest["price"] < last_best.get("price", 10**9):
            should_alert = True

    # Save snapshot + update history
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    history = {"updated_at": now_iso, "latest": results, "best": last_best}
    if cheapest:
        # Update all-time best if improved
        if should_alert:
            history["best"] = cheapest
        else:
            history["best"] = last_best
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

    # Send emails
    if should_alert and cheapest:
        subject = "Shanghai Disneyland — New Cheapest Price"
        html = f"""
        <h3>New Cheapest Price Found</h3>
        <p><strong>Vendor:</strong> {cheapest['vendor']}<br/>
        <strong>Date:</strong> {cheapest['date']}<br/>
        <strong>Price:</strong> {cheapest['price']}<br/>
        <strong>People:</strong> {PEOPLE_SUMMARY}<br/>
        <strong>Link:</strong> <a href="{cheapest['url']}">Open</a></p>
        <hr/>
        <p>Timeseries saved to {HISTORY_PATH}</p>
        """
        send_email(EMAIL_FROM, EMAIL_TO, subject, html)

    # Always send daily snapshot (optional: comment out if noisy)
    table_rows = "".join([
        f"<tr><td>{r['vendor']}</td><td>{r['date']}</td><td>{r['minPrice'] or 'N/A'}</td><td><a href='{r['url']}'>open</a></td></tr>"
        for r in results
    ])
    html = f"<h3>Daily Snapshot</h3><p>{PEOPLE_SUMMARY}</p><table border='1' cellpadding='6' cellspacing='0'><tr><th>Vendor</th><th>Date</th><th>Min Price</th><th>Link</th></tr>{table_rows}</table>"
    send_email(EMAIL_FROM, EMAIL_TO, "Shanghai Disneyland — Daily Snapshot", html)

def send_email(email_from, email_to, subject, html):
    msg = MIMEMultipart("alternative")
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = subject
    part = MIMEText(html, "html", "utf-8")
    msg.attach(part)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        if SMTP_USER and SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(email_from, [email_to], msg.as_string())
        print(f"[INFO] Email sent to {email_to}: {subject}")

if __name__ == "__main__":
    asyncio.run(main())
