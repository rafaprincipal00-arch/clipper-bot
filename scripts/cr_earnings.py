"""Print what Content Rewards shows about our earnings and submissions (read-only, uses the CR_STATE session).

Run by .github/workflows/cr_earnings.yml; the session secret only exists in GitHub Actions. The creator
pages only render when reached through the app's own sidebar (a direct load bounces to the landing page),
so the script opens Discover and clicks Earnings / Submissions / Analytics.
"""
import os
import re
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
            raise SystemExit("SESSION EXPIRED: refresh the CR_STATE secret")
        print(f"landed on {page.url}")
        print(page.inner_text("body")[:1500])
        if "temporarily unavailable" in page.inner_text("body"):
            raise SystemExit("CONTENT REWARDS DOWN (maintenance page); nothing to read today")
        summary = {}
        for name in SECTIONS:
            if not open_section(page, name):
                print(f"===== {name}: sidebar entry not found, skipped")
                continue
            body = page.inner_text("body")
            print(f"===== {name} -> {page.url}")
            print(body[:6000])
            summary.update(read_numbers(name, body))
            if name == "Submissions":
                try:
                    show_reviewed(page)
                except Exception as e:  # the detail panels are a bonus; never lose the summary for them
                    print("show_reviewed failed:", e)
        browser.close()
    # One machine-readable line for scripts/autopilot.py (the PC side reads it from the run log).
    print("CR_SUMMARY " + " ".join(f"{k}={v}" for k, v in summary.items()))
    if "lifetime" not in summary:
        raise SystemExit("earnings page not read")


def open_section(page, name: str) -> bool:
    """Click a sidebar entry. It has been a link and a plain button over time, and an overlay panel covers
    the icons, so look it up several ways and trigger the client-side navigation from the DOM."""
    for loc in (page.get_by_role("link", name=name, exact=True), page.get_by_role("button", name=name, exact=True),
                page.locator("nav, aside").get_by_text(name, exact=True), page.get_by_text(name, exact=True)):
        try:
            if loc.count():
                loc.first.evaluate("el => (el.closest('a,button') || el).click()", timeout=10000)
                page.wait_for_timeout(9000)
                return True
        except Exception as e:
            print(f"{name}: {type(e).__name__}")
    return False


def _after(body: str, label: str) -> str | None:
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    for i, x in enumerate(lines[:-1]):
        if x == label:
            return lines[i + 1].replace(",", "")
    return None


def read_numbers(name: str, body: str) -> dict:
    out = {}
    if name == "Earnings":
        for key, label in (("lifetime", "Lifetime earned"), ("withdraw", "Withdraw"), ("month", "This month")):
            v = _after(body, label)
            if v and re.fullmatch(r"\$[\d.]+", v):
                out[key] = v[1:]
    elif name == "Submissions":
        for key in ("Approved", "Pending", "Rejected", "Clips"):
            v = _after(body, key)
            if v and v.isdigit():
                out[key.lower()] = v
    return out


def show_reviewed(page) -> None:
    """Print the clips the brands already reviewed (Approved / Rejected tabs) with their detail panels."""
    for tab in ("Approved", "Rejected"):
        btn = page.get_by_text(tab, exact=True).first
        if not btn.count():
            continue
        btn.evaluate("el => el.click()")
        page.wait_for_timeout(5000)
        body = page.inner_text("body")
        print(f"===== Submissions / {tab}")
        print(body[body.find("History"):][:5000])
        for i, det in enumerate(page.get_by_text("Rejection reason" if tab == "Rejected" else "View details",
                                                 exact=True).all()[:6]):
            before = page.inner_text("body")
            det.evaluate("el => el.click()")
            page.wait_for_timeout(3000)
            after = page.inner_text("body")
            new = [ln for ln in after.splitlines() if ln.strip() and ln not in before]
            print(f"--- {tab} #{i + 1}:", " | ".join(new)[:1200])
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)


if __name__ == "__main__":
    main()
