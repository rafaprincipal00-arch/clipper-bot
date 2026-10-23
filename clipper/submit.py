"""Submit freshly published posts to their Content Rewards campaign (must happen <30 min after posting).

Content Rewards has no public API: the submit dialog is a Next.js server action, so we drive the real
page headlessly with a saved session (Playwright storage state in env CR_STATE).
"""
import json
import os
import re
import tempfile
from pathlib import Path


def submit(campaign_url: str, links: list[str]) -> dict:
    """Returns {"submitted": [...], "rejected": {link: reason}} or {"error": ...}."""
    state = os.environ.get("CR_STATE")
    if not (state and campaign_url and links):
        return {"error": "skipped (no CR_STATE / campaign / links)"}
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "state.json"
        state_file.write_text(state, encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=str(state_file), viewport={"width": 1280, "height": 900}, locale="en-US")
            page = ctx.new_page()
            # /discover/<id> is the public card; the submit button lives on /c/campaigns/<id>.
            m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", campaign_url)
            if m:
                campaign_url = f"https://contentrewards.com/c/campaigns/{m.group(1)}"
            page.goto(campaign_url, wait_until="domcontentloaded")
            page.wait_for_timeout(7000)
            if "/login" in page.url:
                browser.close()
                return {"error": "Content Rewards session expired: refresh the CR_STATE secret"}
            # A floating chat dock (div.chat-dock) covers the button and swallows the click: remove it.
            hide = "document.querySelectorAll('.chat-dock,[data-dock-slot]').forEach(e => e.remove())"
            page.evaluate(hide)
            pat = re.compile(r"(submit|enviar)", re.I)
            open_btn = None
            for _ in range(3):
                for role in ("button", "link"):
                    c = page.get_by_role(role, name=pat)
                    for i in range(c.count()):
                        if c.nth(i).is_visible():
                            open_btn = c.nth(i)
                            break
                    if open_btn:
                        break
                if open_btn:
                    break
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(1500)
            if open_btn is None:
                names = [x.inner_text()[:40] for x in page.get_by_role("button").all() if x.is_visible()][:40]
                url = page.url
                browser.close()
                return {"error": f"no submit button on {url}; buttons: {names}"}
            page.evaluate(hide)
            open_btn.click(timeout=10000, force=True)
            page.wait_for_timeout(2500)
            dialog = page.get_by_role("dialog").last
            box = dialog.locator("textarea, input[type=url], input[type=text]").first
            box.fill("\n".join(links))
            # The real checkbox is visually hidden behind a styled span: click its label instead.
            dialog.get_by_text(re.compile(r"(I've read the requirements|He leído los requisitos)")).first.click(force=True)
            submit_btn = dialog.get_by_role("button", name=pat).last
            page.evaluate(hide)
            submit_btn.click(timeout=10000, force=True)
            page.wait_for_timeout(4000)
            # Wait out the "Submitting…" state before judging the result.
            for _ in range(30):
                if not (dialog.count() and dialog.is_visible() and re.search(r"Submitting|Enviando", dialog.inner_text())):
                    break
                page.wait_for_timeout(1000)
            # Links that failed stay in the box, with their reason shown in the dialog.
            still_open = dialog.count() and dialog.is_visible()
            remaining = box.input_value() if still_open and box.is_visible() else ""
            text = dialog.inner_text() if still_open else ""
            browser.close()
    left = [l for l in links if l in remaining]
    return {"submitted": [l for l in links if l not in left],
            "rejected": {l: text[-300:] for l in left}}


if __name__ == "__main__":
    import sys
    print(json.dumps(submit(sys.argv[1], sys.argv[2:]), indent=1))
