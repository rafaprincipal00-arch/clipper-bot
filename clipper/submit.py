"""Submit freshly published posts to their Content Rewards campaign (must happen <30 min after posting).

Content Rewards has no public API: the submit dialog is a Next.js server action, so we drive the real
page headlessly with a saved session (Playwright storage state in env CR_STATE).
"""
import base64
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PENDING_PATH = "data/cr_pending.json"


def queue_for_pc(campaign_url: str, links: list[str], reason: str) -> str:
    """CR_STATE expired (or the page changed): push the links to data/cr_pending.json through the GitHub API
    right now, so scripts/cr_submit_watch.py on the PC submits them from Rafa's Brave inside the 30-min
    window. Uses the contents API, so the run's working tree is untouched."""
    repo, tok = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_TOKEN")
    if not (repo and tok):
        return "not queued (no GitHub token)"
    api = f"https://api.github.com/repos/{repo}/contents/{PENDING_PATH}"
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    for _ in range(3):  # another run may write the file at the same time (409/422 -> retry)
        sha, items = None, []
        try:
            with urllib.request.urlopen(urllib.request.Request(api + "?ref=main", headers=hdr), timeout=30) as r:
                cur = json.loads(r.read())
            sha, items = cur["sha"], json.loads(base64.b64decode(cur["content"]) or b"[]")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        now = datetime.now(timezone.utc)
        items = [i for i in items if (now - datetime.fromisoformat(i["posted"])).total_seconds() < 6 * 3600]
        items += [{"campaign": campaign_url, "link": lk, "posted": now.isoformat(timespec="seconds"),
                   "reason": reason[:120]} for lk in links]
        body = {"message": "cr_pending: queue for the PC [skip ci]", "branch": "main",
                "content": base64.b64encode(json.dumps(items, indent=1).encode()).decode()}
        if sha:
            body["sha"] = sha
        try:
            req = urllib.request.Request(api, data=json.dumps(body).encode(), headers=hdr, method="PUT")
            urllib.request.urlopen(req, timeout=30).close()
            return "queued for the PC (Brave)"
        except urllib.error.HTTPError as e:
            if e.code not in (409, 422):
                raise
    return "not queued (write conflicts)"


def submit(campaign_url: str, links: list[str]) -> dict:
    """Returns {"submitted": [...], "rejected": {link: reason}} or {"error": ...}. An error in GitHub
    Actions queues the links for the PC (Rafa's Brave session) instead of losing them."""
    res = _submit(campaign_url, links)
    if res.get("error") and campaign_url and links and os.environ.get("GITHUB_ACTIONS"):
        try:
            res["fallback"] = queue_for_pc(campaign_url, links, res["error"])
        except Exception as e:  # noqa: BLE001
            res["fallback"] = f"queue failed: {e}"[:200]
    return res


def _submit(campaign_url: str, links: list[str]) -> dict:
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
            # An expired session does not always redirect: the page shows the public nav (Sign in / Solutions).
            logged_out = page.get_by_role("link", name="Sign in").count() + page.get_by_role("button", name="Sign in").count()
            if "/login" in page.url or logged_out:
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
                body = page.inner_text("body")[:4000]
                browser.close()
                # Logged-out page: public card with 'Join Campaign' / 'Sign in' instead of our joined view.
                if "Sign in" in names or "6 digit code" in body:
                    return {"error": "Content Rewards session expired: refresh the CR_STATE secret"}
                if "Join Campaign" in names:
                    return {"error": "not joined (or CR_STATE expired): 'Join Campaign' shown instead of Submit"}
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
    res = submit(sys.argv[1], sys.argv[2:])
    print(json.dumps(res, indent=1))
