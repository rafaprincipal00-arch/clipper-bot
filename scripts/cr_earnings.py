"""Print what Content Rewards shows about our earnings and submissions (read-only, uses the CR_STATE session).

Run by .github/workflows/cr_earnings.yml; the session secret only exists in GitHub Actions. The creator
pages only render when reached through the app's own sidebar (a direct load bounces to the landing page),
so the script opens Discover and clicks Earnings / Submissions / Analytics.
"""
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

SECTIONS = ["Earnings", "Submissions", "Analytics", "Home"]


def main() -> None:
    state = os.environ["CR_STATE"]
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        state_file = Path(tmp) / "state.json"
        state_file.write_text(state, encoding="utf-8")
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(state_file), viewport={"width": 1400, "height": 1000},
                                  locale="en-US")
        page = ctx.new_page()
        page.goto("https://contentrewards.com/c/discover", wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        if "/login" in page.url:
            print("SESSION EXPIRED")
            return
        for name in SECTIONS:
            page.get_by_role("link", name=name, exact=True).first.click()
            page.wait_for_timeout(9000)
            print(f"===== {name} -> {page.url}")
            print(page.inner_text("body")[:6000])
        browser.close()


if __name__ == "__main__":
    main()
