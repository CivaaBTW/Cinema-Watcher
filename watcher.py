import os
import re
import time
import requests
from playwright.sync_api import sync_playwright

URLS = [
    "https://www.emperorcinemas.com/cinema/detail?wapid=ECML_WEB_PROD_S_MPS&cinemaId=57011&lang=en_US",
    "https://www.emperorcinemas.com/cinema/detail?wapid=ECML_WEB_PROD_S_MPS&cinemaId=57011&lang=zh_HK",
]

# Specific keywords to avoid false alarms from older Dune re-releases
KEYWORDS = ["part three", "doomsday", "第三部", "末日"]

# Patterns to spot mid-December date tabs if Lisboeta opens them
DEC_DATE_PATTERN = re.compile(r"(16|17|18)\s*dec|dec\s*(16|17|18)|12[/\-](16|17|18)|12月(16|17|18)", re.IGNORECASE)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "").strip()
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
TEST_ALERT = os.environ.get("TEST_ALERT", "false").lower() == "true"

# 24 checks x 30 seconds = ~12 minutes per GitHub Actions cron cycle
MAX_CHECKS = 24
SLEEP_SECONDS = 30


def send_alert(title: str, message: str) -> None:
    sent_any = False

    if NTFY_TOPIC:
        topic = (
            NTFY_TOPIC.removeprefix("https://ntfy.sh/")
            .removeprefix("http://ntfy.sh/")
            .strip("/")
        )
        headers = {
            "Title": title,
            "Priority": "5",
            "Tags": "rotating_light,ticket",
            "Click": URLS[0],
        }
        if NTFY_TOKEN:
            headers["Authorization"] = f"Bearer {NTFY_TOKEN}"

        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
        print(f"ntfy HTTP status: {resp.status_code} | response: {resp.text[:200]}")
        resp.raise_for_status()
        sent_any = True
    else:
        print("Warning: NTFY_TOPIC secret is empty or missing.")

    if DISCORD_WEBHOOK:
        resp = requests.post(
            DISCORD_WEBHOOK,
            json={"content": f"**{title}**\n{message}"},
            timeout=15,
        )
        print(f"Discord HTTP status: {resp.status_code}")
        resp.raise_for_status()
        sent_any = True

    if not sent_any:
        raise RuntimeError(
            "No notification channel configured! Ensure NTFY_TOPIC is saved under "
            "Settings > Secrets and variables > Actions > Repository secrets."
        )


def scan_once(browser) -> list[str]:
    matches = set()
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    )
    context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ("image", "font", "media")
        else route.continue_(),
    )

    page = context.new_page()
    api_blobs = []

    def capture_api(response):
        if "icirena.ai" in response.url and response.request.resource_type in ("xhr", "fetch"):
            try:
                text = response.text()
                # Only keep payloads relevant to Lisboeta Macau (57011) or cinema schedules
                if "57011" in text or "lisboeta" in text.lower() or "schedule" in response.url.lower():
                    api_blobs.append(text)
            except Exception:
                pass

    page.on("response", capture_api)

    for url in URLS:
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1500)

            # If a mid-December date tab appears on Lisboeta's page, click it to trigger its signed schedule call
            try:
                dec_tabs = page.get_by_text(DEC_DATE_PATTERN)
                if dec_tabs.count() > 0:
                    dec_tabs.first.click(timeout=3000)
                    page.wait_for_timeout(2000)
            except Exception:
                pass

            combined_text = (page.inner_text("body") + " " + " ".join(api_blobs)).lower()
            for kw in KEYWORDS:
                if kw in combined_text:
                    matches.add(kw)
        except Exception as exc:
            print(f"Warning checking {url}: {exc}")

    context.close()
    return sorted(matches)


def main() -> None:
    if TEST_ALERT:
        send_alert(
            "Test Alert: Lisboeta Watcher",
            f"Your alert pipeline is working. Tap to open Lisboeta Macau: {URLS[0]}",
        )
        print("Test alert confirmed.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for attempt in range(1, MAX_CHECKS + 1):
                found = scan_once(browser)
                if found:
                    msg = (
                        f"Lisboeta Macau drop detected ({', '.join(found)})! "
                        f"Book immediately: {URLS[0]}"
                    )
                    send_alert("DUNESDAY TICKETS LIVE!", msg)
                    print(f"[Check {attempt}] MATCH FOUND: {found}")
                    return

                print(f"[Check {attempt}/{MAX_CHECKS}] Not live at Lisboeta yet.")
                if attempt < MAX_CHECKS:
                    time.sleep(SLEEP_SECONDS)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
