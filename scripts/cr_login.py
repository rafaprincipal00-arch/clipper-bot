"""Refresh the Content Rewards session used by GitHub Actions (secret CR_STATE).

Opens the bot's OWN visible Chromium window on the Content Rewards login. Rafa logs in himself (email +
code from pepetiktok00.4@gmail.com; the bot never types codes). As soon as the dashboard loads, the
session is saved as the CR_STATE secret and the window closes.

    python scripts/cr_login.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT = r"C:\Program Files\Git\cmd\git.exe" if os.name == "nt" else "git"  # Windows: PATH git pops a picker


def logged_in(page) -> bool:
    return "/c/" in page.url and not (page.get_by_role("link", name="Sign in").count()
                                      or page.get_by_role("button", name="Sign in").count())


def main() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1100, "height": 850}, locale="en-US")
        page = ctx.new_page()
        page.goto("https://contentrewards.com/c/discover", wait_until="domcontentloaded")
        print("Waiting for the login (10 min max)...", flush=True)
        for _ in range(120):
            page.wait_for_timeout(5000)
            try:
                if logged_in(page):
                    break
            except Exception:  # noqa: BLE001  page navigating
                pass
        else:
            browser.close()
            sys.exit("timeout: not logged in")
        page.wait_for_timeout(3000)
        state = json.dumps(ctx.storage_state())
        browser.close()
    out = subprocess.run([GIT, "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True).stdout
    tok = dict(x.split("=", 1) for x in out.splitlines() if "=" in x)["password"]
    with tempfile.TemporaryDirectory():
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        env.update(SECRET_VALUE=state, GH_TOK=tok)
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "set_secret.py"),
                            "rafaprincipal00-arch/clipper-bot", "CR_STATE"], env=env, capture_output=True, text=True)
    print("CR_STATE saved:", r.stdout.strip() or r.stderr.strip()[-200:], flush=True)
    time.sleep(1)


if __name__ == "__main__":
    main()
