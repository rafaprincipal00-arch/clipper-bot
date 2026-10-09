"""Post to TikTok in the background with the bot's OWN browser: never the user's Brave, mouse or keyboard.

Each account has its own Chromium profile in data/tt_profiles/<n> (Playwright's bundled Chromium).
Posting runs headless: no window, no focus change, input goes through the DevTools protocol.

    python scripts/tiktok_bg.py login 1     # one-time: opens a separate window on the top monitor,
                                            # the user signs in to TikTok there, then closes it
    python scripts/tiktok_bg.py check       # which accounts are signed in
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "data" / "tt_profiles"
UPLOAD = "https://www.tiktok.com/tiktokstudio/upload"
HANDLES = {1: "pepe854146", 2: "streammoments.daily", 3: "rafael.benitez656"}
DEBUG_SHOTS = False
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


def add_song(page, mood: str | None, log=print) -> str | None:
    """Add a trending song from TikTok's own (licensed) library in Studio's editor, quiet under the voice.
    Songs per mood live in config/music.json. Returns "title - artist" or None (posts with the clip's audio)."""
    cfg = json.loads((ROOT / "config" / "music.json").read_text(encoding="utf-8"))
    songs = cfg["tiktok"].get(mood or "", []) + [s for m in cfg["tiktok"].values() for s in m]
    songs = list(dict.fromkeys(tuple(s) for s in songs))
    cookies = page.get_by_role("button", name="Decline optional cookies")
    if cookies.count():
        cookies.first.click()
    sounds = page.get_by_role("button", name="Sounds", exact=True)
    if not sounds.count():
        log("  music: no Sounds button, posting with the clip's own audio")
        return None
    sounds.first.click()
    search = page.get_by_placeholder("Search sounds")
    try:
        search.wait_for(timeout=30_000)
    except Exception:  # noqa: BLE001 — editor did not open
        log("  music: sound editor did not open")
        return None
    page.wait_for_timeout(2000)
    for title, artist in songs:
        search.fill(f"{title} {artist}")
        search.press("Enter")
        page.wait_for_timeout(6000)
        # The result row holds the title text and a "+" button: click the button of the first matching row.
        added = page.evaluate("""([title, artist]) => {
            const norm = s => (s || "").toLowerCase();
            const rows = [...document.querySelectorAll("div")].filter(d => d.offsetWidth > 0
                && d.querySelector("button") && norm(d.innerText).startsWith(norm(title))
                && norm(d.innerText).includes(norm(artist).split(" ")[0]) && d.innerText.length < 160);
            rows.sort((a, b) => a.innerText.length - b.innerText.length);
            const btn = rows.length && [...rows[0].querySelectorAll("button")].pop();
            if (!btn) return false;
            btn.click();
            return true;
        }""", [title, artist])
        if not added:
            continue
        page.wait_for_timeout(5000)
        nums = page.locator("input[type=text]").filter(has_not_text="x")
        boxes = [b for b in nums.all() if b.is_visible() and (b.get_attribute("value") or "") in ("0", "0.0")]
        if boxes:  # Volume (dB), fade-in (s), fade-out (s)
            boxes[0].fill(cfg.get("tiktok_db", "-14"))
            boxes[0].press("Enter")
            if len(boxes) >= 3:
                boxes[2].fill("1")
                boxes[2].press("Enter")
        page.wait_for_timeout(1500)
        if DEBUG_SHOTS:
            page.screenshot(path=str(ROOT / "data" / "tiktok_song_before_save.png"))
        page.get_by_role("button", name="Save", exact=True).first.click()
        page.wait_for_timeout(6000)
        log(f"  music: {title} - {artist} (TikTok library) at {cfg.get('tiktok_db', '-14')} dB")
        return f"{title} - {artist}"
    log("  music: none of the songs found; posting with the clip's own audio")
    cancel = page.get_by_role("button", name="Cancel", exact=True)
    if cancel.count():
        cancel.first.click()
        page.wait_for_timeout(2000)
        for label in ("Discard", "Leave", "Exit"):  # "discard edits?" confirmation
            b = page.get_by_role("button", name=label, exact=True)
            if b.count() and b.last.is_visible():
                b.last.click()
                break
    return None


def post(account: int, video: Path, caption: str, log=print, mood: str | None = None, song: bool = False) -> dict:
    """Upload + publish publicly. `song=True` adds a TikTok-library song for `mood` (only for clips
    rendered without their own music bed). Returns {"url", "music", "check"}."""
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
            music = add_song(page, mood, log) if song else None
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
            return {"url": url, "music": music, "check": "ok"}
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
