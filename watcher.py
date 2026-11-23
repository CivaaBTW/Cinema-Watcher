import os
import time
import requests
from playwright.sync_api import sync_playwright

URLS = [
    "https://www.emperorcinemas.com/cinema/detail?wapid=ECML_WEB_PROD_S_MPS&cinemaId=57011&lang=en_US",
    "https://www.emperorcinemas.com/cinema/detail?wapid=ECML_WEB_PROD_S_MPS&cinemaId=57011&lang=zh_HK",
]

# Specific keywords to avoid false alarms from older Dune re-releases
KEYWORDS = ["part three", "doomsday", "第三部", "末日"]

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
TEST_ALERT = os.environ.get("TEST_ALERT", "false").lower() == "true"

# 27 checks x 30 seconds = 13.5 minutes per GitHub Actions cron cycle
MAX_CHECKS = 27
SLEEP_SECONDS = 30


def send_ntfy(title: str, message: str) -> None:
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": "max",
            "Tags": "rotating_light,ticket",
            "Click": URLS[0],
        },
        timeout=15,
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
    # Abort images, fonts, and media to speed up page loads
    context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ("image", "font", "media")
        else route.continue_(),
    )

    page = context.new_page()
    xhr_blobs = []

    def capture_xhr(response):
        if response.request.resource_type in ("xhr", "fetch"):
            try:
                xhr_blobs.append(response.text())
            except Exception:
                pass

    page.on("response", capture_xhr)

    for url in URLS:
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1500)
            combined_text = (page.inner_text("body") + " " +
                             " ".join(xhr_blobs)).lower()
            for kw in KEYWORDS:
                if kw in combined_text:
                    matches.add(kw)
        except Exception as exc:
            print(f"Warning checking {url}: {exc}")

    context.close()
    return sorted(matches)


def main() -> None:
    if TEST_ALERT:
        send_ntfy(
            "Test Alert: Lisboeta Watcher",
            "Your ntfy connection is working. Tap to open Lisboeta Macau.",
        )
        print("Test alert sent successfully.")
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
                    send_ntfy("DUNESDAY TICKETS LIVE!", msg)
                    print(f"[Check {attempt}] MATCH FOUND: {found}")
                    return

                print(f"[Check {attempt}/{MAX_CHECKS}] Not live yet.")
                if attempt < MAX_CHECKS:
                    time.sleep(SLEEP_SECONDS)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
