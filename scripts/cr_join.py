"""Join Content Rewards campaigns (no-application ones) and print their unlocked rules.

Usage (GitHub Actions, CR_STATE session): python scripts/cr_join.py <campaign_id> [<campaign_id> ...]
Only clicks "Join Campaign" and any "I agree / Join" confirmation inside the join dialog.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def main(ids: list[str]) -> None:
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        sf = Path(tmp) / "state.json"
        sf.write_text(os.environ["CR_STATE"], encoding="utf-8")
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(sf), viewport={"width": 1400, "height": 1000}, locale="en-US")
        page = ctx.new_page()
        for cid in ids:
            url = f"https://contentrewards.com/c/campaigns/{cid}"
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(7000)
            if "/login" in page.url:
                raise SystemExit("SESSION EXPIRED")
            join = page.get_by_role("button", name=re.compile(r"^Join Campaign$"))
            print(f"===== {cid} join button: {join.count()}")
            if join.count():
                join.first.evaluate("el => el.click()")
                page.wait_for_timeout(4000)
                dialog = page.get_by_role("dialog")
                if dialog.count():
                    print("DIALOG:", dialog.first.inner_text()[:1500])
                    for box in dialog.first.locator("input[type=checkbox]").all():
                        box.evaluate("el => { if (!el.checked) el.click(); }")
                    confirm = dialog.first.get_by_role("button", name=re.compile(r"Join|Agree|Accept|Continue|Confirm"))
                    if confirm.count():
                        confirm.last.evaluate("el => el.click()")
                        page.wait_for_timeout(5000)
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(7000)
            body = page.inner_text("body").split("Connect Discord", 1)[-1]
            print("JOINED:", "Submit clip" in body or "Leave campaign" in body)
            print(body[:5000])
            # Expand the unlocked rule/requirement sections.
            for t in ("Content requirements", "Creator requirements"):
                el = page.get_by_text(t, exact=True)
                if el.count():
                    el.first.evaluate("el => el.click()")
                    page.wait_for_timeout(2500)
                    print(f"--- {t}:", page.inner_text("body").split(t, 1)[-1][:2500])
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
