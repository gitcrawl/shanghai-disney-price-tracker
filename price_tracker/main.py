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
import ssl

# -------- CONFIG VIA ENV --------
DATES = os.getenv("DATES", "2025-09-01,2025-09-02").split(",")
KLOOK_URL = os.getenv("KLOOK_URL", "https://REPLACE-KLOOK-URL")
TRIPCOM_URL = os.getenv("TRIPCOM_URL", "https://REPLACE-TRIPCOM-URL?date={DATE}")
EMAIL_TO = os.getenv("EMAIL_TO", "you@example.com").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", "alerts@example.com").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.example.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_SECURE = os.getenv("SMTP_SECURE", "TLS").upper()  # TLS | SSL | NONE
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() in ("1", "true", "yes")
PEOPLE_SUMMARY = os.getenv("PEOPLE_SUMMARY", "2 adults")
HISTORY_PATH = Path(os.getenv("HISTORY_PATH", "data/history.json"))

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"

# Regex for proper currency amounts (requires symbol, avoids lone "1")
PRICE_RE = re.compile(r"(?:A\$|AU\$|\$|¥|CNY)\s*([1-9]\d(?:,\d{3})*|\d{3,})(?:\.\d{1,2})?")

async def fetch_min_price(page, url: str) -> float | None:
    try:
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(2000)  # give JS a moment to render

        prices = []

        # --- Pass 1: scrape visible text nodes likely containing prices
        # Grab lots of candidate texts (buttons, spans, divs)
        candidate_texts = await page.locator("text=/¥|AU\\$|A\\$|\\$/").all_text_contents()
        for t in candidate_texts:
            for m in PRICE_RE.finditer(t):
                try:
                    val = float(m.group(1).replace(",", ""))
                    if val > 40:  # filter tiny junk like "1"
                        prices.append(val)
                except:
                    pass

        # --- Pass 2: regex over full HTML as fallback
        if not prices:
            html = await page.content()
            for m in PRICE_RE.finditer(html):
                try:
                    val = float(m.group(1).replace(",", ""))
                    if val > 40:
                        prices.append(val)
                except:
                    pass

        # Heuristic guardrails: ticket prices won't be ridiculous.
        prices = [p for p in prices if 10 < p < 5000]

        return min(prices) if prices else None

    except Exception as e:
        print(f"[WARN] Failed to fetch {url}: {e}")
        return None

async def main():
    targets = []
    for d in [x.strip() for x in DATES if x.strip()]:
        klook = KLOOK_URL.format(DATE=d) if "{DATE}" in KLOOK_URL else KLOOK_URL
        trip = TRIPCOM_URL.format(DATE=d) if TRIPCOM_URL else None
        if klook:
            targets.append(("KLOOK", d, klook))
        if trip:
            targets.append(("TRIPCOM", d, trip))

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        for vendor, date_str, url in targets:
            if not url:
                continue
            price = await fetch_min_price(page, url)
            print(f"{vendor} {date_str} -> {price} ({url})")
            results.append({"vendor": vendor, "date": date_str, "url": url, "minPrice": price})
        await browser.close()

    # Pick cheapest
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

    # Save snapshot
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    history = {"updated_at": now_iso, "latest": results, "best": last_best}
    if cheapest:
        if should_alert:
            history["best"] = cheapest
        else:
            history["best"] = last_best
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

    # Send emails if enabled
    if EMAIL_ENABLED:
        if should_alert and cheapest:
            subject = "Shanghai Disneyland — New Cheapest Price"
            html = f"""
            <h3>New Cheapest Price Found</h3>
            <p><strong>Vendor:</strong> {cheapest['vendor']}<br/>
            <strong>Date:</strong> {cheapest['date']}<br/>
            <strong>Price:</strong> {cheapest['price']}<br/>
            <strong>People:</strong> {PEOPLE_SUMMARY}<br/>
            <strong>Link:</strong> <a href="{cheapest['url']}">Open</a></p>
            """
            safe_send_email(EMAIL_FROM, EMAIL_TO, subject, html)

        # Daily snapshot
        table_rows = "".join([
            f"<tr><td>{r['vendor']}</td><td>{r['date']}</td><td>{r['minPrice'] or 'N/A'}</td><td><a href='{r['url']}'>open</a></td></tr>"
            for r in results
        ])
        html = f"<h3>Daily Snapshot</h3><p>{PEOPLE_SUMMARY}</p><table border='1'><tr><th>Vendor</th><th>Date</th><th>Min Price</th><th>Link</th></tr>{table_rows}</table>"
        safe_send_email(EMAIL_FROM, EMAIL_TO, "Shanghai Disneyland — Daily Snapshot", html)
    else:
        print("[INFO] EMAIL_ENABLED=false — skipping emails.")

def safe_send_email(email_from, email_to, subject, html):
    try:
        send_email(email_from, email_to, subject, html)
    except Exception as e:
        print(f"[WARN] Email send failed but continuing: {e}")

def send_email(email_from, email_to, subject, html):
    msg = MIMEMultipart("alternative")
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = subject
    part = MIMEText(html, "html", "utf-8")
    msg.attach(part)

    if SMTP_SECURE == "SSL":
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(email_from, [email_to], msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as server:
            if SMTP_SECURE == "TLS":
                server.starttls(context=ssl.create_default_context())
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(email_from, [email_to], msg.as_string())
    print(f"[INFO] Email sent to {email_to}: {subject}")

if __name__ == "__main__":
    asyncio.run(main())
