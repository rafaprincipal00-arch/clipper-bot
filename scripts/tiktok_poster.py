"""Post today's clips to TikTok from the PC at staggered times, then submit each link to Content Rewards.

Why from the PC: the TikTok API app is unaudited (drafts only), so posting publicly needs a real
logged-in browser. Each TikTok account has its own Brave profile under data/tt_profiles/<n>
(Brave, never committed). The clipper workflow publishes YouTube and leaves TikTok as "scheduled (PC poster)".

    python scripts/tiktok_poster.py login 1      # one-off: opens Brave so the user logs into account 1
    python scripts/tiktok_poster.py check        # which profiles are logged in
    python scripts/tiktok_poster.py run          # daemon: wait for today's clips, post at planned times
    python scripts/tiktok_poster.py post <file>  # post one clip now (manual)

Log: data/tiktok_poster.log. Plan/state: data/tiktok_plan.json (both local only).
"""
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "rafaprincipal00-arch/clipper-bot"
PROFILES = ROOT / "data" / "tt_profiles"
PLAN = ROOT / "data" / "tiktok_plan.json"
LOG = ROOT / "data" / "tiktok_poster.log"
WORK = ROOT / "work" / "tiktok"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?lang=en"
# Posting windows (local time): first post ~1 h after the clips exist, then spread over the day.
FIRST_DELAY_MIN = (45, 90)
SPACING_MIN = (110, 170)
LAST_HOUR = 23
NO_WINDOW = 0x08000000
# Brave (the user's browser) with its own per-account profile; his normal Brave profile is never touched.
BROWSER = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"


def log(*a: object) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(map(str, a))
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------- GitHub ----------------
def github_token() -> str:
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("no GitHub credential stored in git")


def gh(path: str, body: dict | None = None) -> dict | list | None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}", data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {github_token()}", "Accept": "application/vnd.github+json"},
        method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def remote_clips() -> list[dict]:
    """data/clips.json on main (the clipper run commits it at the end)."""
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/data/clips.json",
                                 headers={"Authorization": f"Bearer {github_token()}",
                                          "Accept": "application/vnd.github.raw"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def submit_to_cr(campaign: str, link: str) -> None:
    gh("actions/workflows/submit.yml/dispatches", {"ref": "main", "inputs": {"campaign": campaign, "links": link}})


# ---------------- plan ----------------
def load_plan() -> dict:
    if PLAN.exists():
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        if plan.get("date") == datetime.now().date().isoformat():
            return plan
    return {"date": datetime.now().date().isoformat(), "items": []}


def save_plan(plan: dict) -> None:
    PLAN.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")


def todays_clips() -> list[dict]:
    today = datetime.now().astimezone().date()
    out = []
    for e in remote_clips():
        created = datetime.fromisoformat(e["created"]).astimezone()
        if created.date() == today and e.get("account") and e.get("video_url") \
                and (e.get("posts") or {}).get("tiktok", "").startswith("scheduled"):
            out.append(e)
    return sorted(out, key=lambda e: e["account"])


def schedule(plan: dict, clips: list[dict]) -> None:
    known = {i["file"] for i in plan["items"]}
    last = max((datetime.fromisoformat(i["at"]) for i in plan["items"]), default=None)
    for e in clips:
        if e["file"] in known:
            continue
        if last is None:
            at = datetime.now() + timedelta(minutes=random.randint(*FIRST_DELAY_MIN))
        else:
            at = last + timedelta(minutes=random.randint(*SPACING_MIN))
        at = min(at, datetime.now().replace(hour=LAST_HOUR, minute=random.randint(0, 40)))
        last = at
        plan["items"].append({"file": e["file"], "account": e["account"], "video_url": e["video_url"],
                              "caption": e["caption"], "campaign": e.get("campaign"),
                              "at": at.isoformat(timespec="seconds"), "status": "pending"})
        log(f"planned {e['file']} -> TikTok account {e['account']} at {at:%H:%M}")
    save_plan(plan)


# ---------------- browser ----------------
def profile_dir(account: int) -> Path:
    d = PROFILES / str(account)
    d.mkdir(parents=True, exist_ok=True)
    return d


def open_ctx(p, account: int, headless: bool):
    """Brave with a persistent per-account profile, on the TOP monitor."""
    return p.chromium.launch_persistent_context(
        str(profile_dir(account)), executable_path=BROWSER, headless=headless,
        viewport=None if not headless else {"width": 1280, "height": 900},
        args=["--window-position=40,40", "--window-size=1280,900", "--disable-blink-features=AutomationControlled",
              "--no-first-run", "--no-default-browser-check"],
        ignore_default_args=["--enable-automation"], locale="en-US")


def logged_in(page) -> bool:
    page.goto(UPLOAD_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    return "login" not in page.url and page.locator("input[type=file]").count() > 0


def username(page) -> str | None:
    try:
        page.goto("https://www.tiktok.com/profile", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if "/@" in page.url:
            return page.url.split("/@", 1)[1].split("?")[0].split("/")[0]
    except Exception:  # noqa: BLE001 — informational only
        pass
    return None


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r:
        dest.write_bytes(r.read())
    return dest


def post_video(account: int, video: Path, caption: str, headless: bool = True) -> str:
    """Upload + publish publicly via TikTok Studio. Returns the public post URL."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = open_ctx(p, account, headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if not logged_in(page):
                raise RuntimeError(f"TikTok account {account} is not logged in (run: tiktok_poster.py login {account})")
            page.locator("input[type=file]").first.set_input_files(str(video))
            # Caption editor (draft.js contenteditable) appears once the file is accepted.
            editor = page.locator("div[contenteditable='true']").first
            editor.wait_for(timeout=120_000)
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
            # Wait for the upload to finish: the Post button becomes enabled.
            post_btn = page.locator("button[data-e2e='post_video_button'], button:has-text('Post')").last
            for _ in range(180):
                if post_btn.is_enabled() and not page.get_by_text("Uploading").count():
                    break
                page.wait_for_timeout(1000)
            page.wait_for_timeout(3000)
            post_btn.click()
            page.wait_for_timeout(4000)
            # "Post now" confirmation shows up on some accounts (e.g. content check still running).
            for label in ("Post now", "Publicar ahora"):
                b = page.get_by_role("button", name=label)
                if b.count():
                    b.first.click()
                    page.wait_for_timeout(3000)
            page.wait_for_url("**/tiktokstudio/content**", timeout=120_000)
            user = username(page)
            return latest_post_url(page, user)
        finally:
            ctx.close()


def latest_post_url(page, user: str | None) -> str:
    """Newest video link on the account's profile (TikTok needs a few seconds to list it)."""
    if not user:
        raise RuntimeError("posted, but could not read the username to find the link")
    for _ in range(12):
        page.goto(f"https://www.tiktok.com/@{user}", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        hrefs = page.eval_on_selector_all("a[href*='/video/']", "els => els.map(e => e.href)")
        vids = sorted({h.split("?")[0] for h in hrefs if f"/@{user}/video/" in h},
                      key=lambda h: int(h.rsplit("/", 1)[1]), reverse=True)
        if vids:
            return vids[0]
        time.sleep(10)
    raise RuntimeError("posted, but the video did not show up on the profile yet")


# ---------------- commands ----------------
def do_item(plan: dict, item: dict) -> None:
    item["status"] = "posting"
    save_plan(plan)
    try:
        video = download(item["video_url"], WORK / item["file"])
        url = post_video(item["account"], video, item["caption"])
        item.update(status="posted", url=url, posted_at=datetime.now().isoformat(timespec="seconds"))
        log(f"posted {item['file']} -> {url}")
        if item.get("campaign"):
            submit_to_cr(item["campaign"], url)
            item["submitted"] = True
            log(f"Content Rewards submit dispatched for {url}")
        video.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 — keep the daemon alive; retried once later
        item["tries"] = item.get("tries", 0) + 1
        item["status"] = "failed" if item["tries"] >= 2 else "pending"
        item["error"] = str(e)[:300]
        if item["status"] == "pending":
            item["at"] = (datetime.now() + timedelta(minutes=20)).isoformat(timespec="seconds")
        log(f"FAILED {item['file']} (try {item['tries']}): {e}")
    save_plan(plan)


def run() -> None:
    """Started at logon. Waits (up to 3 h) for today's clips, plans them, posts each at its time."""
    log("poster started")
    deadline = datetime.now() + timedelta(hours=3)
    plan = load_plan()
    while True:
        try:
            clips = todays_clips()
        except (OSError, urllib.error.URLError, ValueError) as e:
            log("cannot read clips.json:", e)
            clips = []
        schedule(plan, clips)
        pending = [i for i in plan["items"] if i["status"] == "pending"]
        if len(plan["items"]) >= 3 and not pending:
            log("all of today's clips handled; exiting")
            return
        if not plan["items"] and datetime.now() > deadline:
            log("no clips for today after 3 h; exiting")
            return
        due = [i for i in pending if datetime.fromisoformat(i["at"]) <= datetime.now()]
        for item in due[:1]:
            do_item(plan, item)
        time.sleep(60)


def login(account: int) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = open_ctx(p, account, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")
        print(f"Log into TikTok account {account} in the Brave window; it closes by itself once done.")
        for _ in range(600):
            time.sleep(3)
            try:
                if page.is_closed():
                    break
                cookies = ctx.cookies("https://www.tiktok.com")
                if any(c.get("name") == "sessionid" and c.get("value") for c in cookies):
                    page.wait_for_timeout(4000)
                    print("logged in as", username(page))
                    break
            except Exception:  # noqa: BLE001 — window closed by the user
                break
        ctx.close()


def check() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        for n in (1, 2, 3):
            ctx = open_ctx(p, n, headless=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ok = logged_in(page)
            print(f"account {n}: {'logged in as ' + str(username(page)) if ok else 'NOT logged in'}")
            ctx.close()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "login":
        login(int(sys.argv[2]))
    elif cmd == "check":
        check()
    elif cmd == "post":
        e = next(x for x in remote_clips() if x["file"] == sys.argv[2])
        plan = load_plan()
        item = {"file": e["file"], "account": e.get("account") or 1, "video_url": e["video_url"],
                "caption": e["caption"], "campaign": e.get("campaign"), "at": datetime.now().isoformat(),
                "status": "pending"}
        plan["items"].append(item)
        do_item(plan, item)
    else:
        run()


if __name__ == "__main__":
    main()
