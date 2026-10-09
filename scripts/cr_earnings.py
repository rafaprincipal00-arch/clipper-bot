"""Print what Content Rewards shows about our earnings and submissions (read-only, uses the CR_STATE session).

Run by .github/workflows/cr_earnings.yml; the session secret only exists in GitHub Actions.
"""
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["https://contentrewards.com/dashboard", "https://contentrewards.com/earnings",
         "https://contentrewards.com/submissions", "https://contentrewards.com/wallet",
         "https://contentrewards.com/profile"]


def main() -> None:
    state = os.environ["CR_STATE"]
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        state_file = Path(tmp) / "state.json"
        state_file.write_text(state, encoding="utf-8")
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(state_file), viewport={"width": 1280, "height": 900},
                                  locale="en-US")
        page = ctx.new_page()
        for url in PAGES:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(8000)
            print(f"===== {url} -> {page.url}")
            if "/login" in page.url:
                print("SESSION EXPIRED")
                break
            print(page.inner_text("body")[:4000])
            links = page.eval_on_selector_all("a[href]", "els => [...new Set(els.map(e => e.href))]")
            print("LINKS:", [h for h in links if "contentrewards.com" in h][:40])
        browser.close()


if __name__ == "__main__":
    main()
