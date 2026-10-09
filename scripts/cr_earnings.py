"""Print what Content Rewards shows about our earnings and submissions (read-only, uses the CR_STATE session).

Run by .github/workflows/cr_earnings.yml; the session secret only exists in GitHub Actions.
"""
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["https://contentrewards.com/discover", "https://contentrewards.com/discover/1634558e-eae2-4d03-bd7d-a51ab44999a1"]
KEYS = ("earn", "wallet", "payout", "submission", "balance", "account", "stats", "analytics", "my-")


def main() -> None:
    state = os.environ["CR_STATE"]
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        state_file = Path(tmp) / "state.json"
        state_file.write_text(state, encoding="utf-8")
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(state_file), viewport={"width": 1280, "height": 900},
                                  locale="en-US")
        page = ctx.new_page()
        seen: set[str] = set()
        queue = list(PAGES)
        while queue and len(seen) < 9:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(8000)
            print(f"===== {url} -> {page.url}")
            if "/login" in page.url:
                print("SESSION EXPIRED")
                break
            print(page.inner_text("body")[:4000])
            links = page.eval_on_selector_all("a[href]", "els => [...new Set(els.map(e => e.href))]")
            print("LINKS:", [h for h in links if "contentrewards.com" in h][:60])
            queue += [h for h in links if "contentrewards.com" in h and any(k in h.lower() for k in KEYS)
                      and h not in seen]
        browser.close()


if __name__ == "__main__":
    main()
