"""Post to TikTok in the background with the bot's OWN browser: never the user's Brave, mouse or keyboard.

Each account has its own Chromium profile in data/tt_profiles/<n> (Playwright's bundled Chromium).
Posting runs headless: no window, no focus change, input goes through the DevTools protocol.

    python scripts/tiktok_bg.py login 1     # one-time: opens a separate window on the top monitor,
                                            # the user signs in to TikTok there, then closes it
    python scripts/tiktok_bg.py check       # which accounts are signed in
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "data" / "tt_profiles"
UPLOAD = "https://www.tiktok.com/tiktokstudio/upload"
HANDLES = {1: "pepe854146", 2: "streammoments.daily", 3: "rafael.benitez656"}
ARGS = ["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
# Headless Chromium announces itself as "HeadlessChrome"; TikTok's login/risk checks reject that session.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/148.0.0.0 Safari/537.36")


def profile(account: int) -> Path:
    d = PROFILES / str(account)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ctx(p, account: int):
    return p.chromium.launch_persistent_context(
        str(profile(account)), headless=True, args=ARGS, ignore_default_args=["--enable-automation"],
        viewport={"width": 1366, "height": 900}, locale="en-US", user_agent=UA)


def _signed_in(page) -> bool:
    page.goto(UPLOAD, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(7000)
    return "login" not in page.url and page.locator("input[type=file]").count() > 0


def _dismiss(page) -> None:
    for label in ("Got it", "OK", "Not now", "Cancel", "Close", "Entendido", "Ahora no", "Cancelar", "Cerrar"):
        b = page.get_by_role("button", name=label, exact=True)
        if b.count() and b.first.is_visible():
            try:
                b.first.click(timeout=2000)
                page.wait_for_timeout(500)
            except Exception:  # noqa: BLE001 — optional popups
                pass


def _latest(page, handle: str) -> str:
    # TikTok Studio's content list (the public profile renders no video grid in a headless browser).
    for _ in range(12):
        page.goto("https://www.tiktok.com/tiktokstudio/content", wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(6000)
        hrefs = page.eval_on_selector_all("a[href*='/video/']", "els => els.map(e => e.href)")
        vids = sorted({h.split("?")[0] for h in hrefs if f"/@{handle}/video/" in h},
                      key=lambda h: int(h.rsplit("/", 1)[1]), reverse=True)
        if vids:
            return vids[0]
        time.sleep(10)
    raise RuntimeError("posted, but the video did not show up on the profile yet")


def post(account: int, video: Path, caption: str, log=print) -> dict:
    """Upload + publish publicly. Returns {"url", "music": None, "check"}."""
    from playwright.sync_api import sync_playwright

    handle = HANDLES[account]
    with sync_playwright() as p:
        ctx = _ctx(p, account)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if not _signed_in(page):
                raise RuntimeError(f"account {account} (@{handle}) is not signed in: run tiktok_bg.py login {account}")
            page.locator("input[type=file]").first.set_input_files(str(video))
            editor = page.locator("div[contenteditable='true']").first
            editor.wait_for(timeout=180_000)
            _dismiss(page)
            editor.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            for chunk in caption.replace("\n", " ").split(" "):
                if not chunk:
                    continue
                page.keyboard.type(chunk, delay=15)
                if chunk.startswith("#"):
                    page.wait_for_timeout(1200)
                    page.keyboard.press("Escape")  # close hashtag suggestions
                page.keyboard.type(" ")
            btn = page.locator("button[data-e2e='post_video_button']")
            if not btn.count():
                btn = page.get_by_role("button", name="Post", exact=True)
            for _ in range(300):  # upload + content check
                if btn.first.is_enabled() and not page.get_by_text("Uploading").count():
                    break
                page.wait_for_timeout(1000)
            page.wait_for_timeout(3000)
            _dismiss(page)
            btn.first.click()
            page.wait_for_timeout(4000)
            for label in ("Post now", "Publicar ahora"):
                b = page.get_by_role("button", name=label)
                if b.count():
                    b.first.click()
                    page.wait_for_timeout(3000)
            page.wait_for_url("**/tiktokstudio/content**", timeout=180_000)
            log(f"  published on @{handle}")
            url = _latest(page, handle)
            return {"url": url, "music": None, "check": "ok"}
        except Exception:
            page.screenshot(path=str(ROOT / "data" / f"tiktok_fail_{account}.png"))
            raise
        finally:
            ctx.close()


def login(account: int) -> None:
    """Separate Chromium window (not Brave) on the top monitor; the user signs in, then closes it.
    Started as a plain process (no automation flags) so Google's sign-in accepts it."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        exe = p.chromium.executable_path
    subprocess.Popen([exe, f"--user-data-dir={profile(account)}", "--window-position=60,60", "--window-size=1200,900",
                      "--no-first-run", "--no-default-browser-check", "https://www.tiktok.com/login"])


def check() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        for a in HANDLES:
            ctx = _ctx(p, a)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                print(a, HANDLES[a], "signed in" if _signed_in(page) else "NOT signed in")
            finally:
                ctx.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "login":
        login(int(sys.argv[2]))
    else:
        check()
