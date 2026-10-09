"""Post today's clips to TikTok from the PC at staggered times, then submit each link to Content Rewards.

Why from the PC: the TikTok API app is unaudited (drafts only), so public posts go through TikTok Studio
in the user's own Brave (scripts/tiktok_brave.py: one Brave profile per TikTok account, background window
on the top monitor, licensed song from TikTok's library). The clipper workflow publishes YouTube and leaves
TikTok as "scheduled (PC poster)".

    python scripts/tiktok_poster.py run          # daemon (started at logon): post each clip at its planned time
    python scripts/tiktok_poster.py post <file>  # post one clip now

Log: data/tiktok_poster.log. Plan/state: data/tiktok_plan.json (both local only).
"""
import json
import random
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
REPO = "rafaprincipal00-arch/clipper-bot"
PLAN = ROOT / "data" / "tiktok_plan.json"
LOG = ROOT / "data" / "tiktok_poster.log"
WORK = ROOT / "work" / "tiktok"
# Posting windows (local time): first post ~1 h after the clips exist, the rest spread evenly until
# LAST_POST, with some jitter. EXPECTED = clips per day (3 per TikTok account).
FIRST_DELAY_MIN = (45, 90)
MIN_SPACING_MIN = 35
LAST_POST = (23, 40)
EXPECTED = 9
NO_WINDOW = 0x08000000


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
    return sorted(out, key=lambda e: e["created"])


def schedule(plan: dict, clips: list[dict]) -> None:
    known = {i["file"] for i in plan["items"]}
    last = max((datetime.fromisoformat(i["at"]) for i in plan["items"]), default=None)
    end = datetime.now().replace(hour=LAST_POST[0], minute=LAST_POST[1], second=0)
    for e in clips:
        if e["file"] in known:
            continue
        if last is None:
            at = datetime.now() + timedelta(minutes=random.randint(*FIRST_DELAY_MIN))
        else:
            left = max(1, EXPECTED - len(plan["items"]))  # posts still to place, this one included
            even = (end - last).total_seconds() / 60 / left
            at = last + timedelta(minutes=max(MIN_SPACING_MIN, even * random.uniform(0.85, 1.15)))
        at = max(datetime.now() + timedelta(minutes=2), min(at, end))
        last = at
        plan["items"].append({"file": e["file"], "account": e["account"], "video_url": e.get("tiktok_url") or e["video_url"],
                              "caption": e.get("tiktok_caption") or e["caption"], "campaign": e.get("campaign"),
                              "mood": e.get("mood"), "song": bool(e.get("tiktok_url")),
                              "at": at.isoformat(timespec="seconds"), "status": "pending"})
        log(f"planned {e['file']} -> TikTok account {e['account']} at {at:%H:%M}")
    save_plan(plan)


# ---------------- browser ----------------
def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r:
        dest.write_bytes(r.read())
    return dest


# ---------------- commands ----------------
def do_item(plan: dict, item: dict) -> None:
    item["status"] = "posting"
    save_plan(plan)
    try:
        video = download(item["video_url"], WORK / item["file"])
        import tiktok_bg  # the bot's own headless browser; never the user's Brave, mouse or keyboard
        res = tiktok_bg.post(item["account"], video, item["caption"], log, mood=item.get("mood"),
                             song=item.get("song", False))
        url = res["url"]
        item.update(status="posted", url=url, music=res["music"], posted_at=datetime.now().isoformat(timespec="seconds"))
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
        log("  " + traceback.format_exc().strip().replace("\n", "\n  ")[-1500:])
    save_plan(plan)


def run() -> None:
    """Started at logon. Waits (up to 3 h) for today's clips, plans them, posts each at its time.
    Exits when EXPECTED clips are handled or, if the cloud run made fewer, at the end of the day."""
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
        if len(plan["items"]) >= EXPECTED and not pending:
            log("all of today's clips handled; exiting")
            return
        if not plan["items"] and datetime.now() > deadline:
            log("no clips for today after 3 h; exiting")
            return
        last_call = datetime.now().replace(hour=LAST_POST[0], minute=LAST_POST[1]) + timedelta(minutes=15)
        if plan["items"] and not pending and datetime.now() > last_call:
            log("end of the day; exiting")
            return
        due = [i for i in pending if datetime.fromisoformat(i["at"]) <= datetime.now()]
        for item in due[:1]:
            do_item(plan, item)
        time.sleep(60)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "post":
        e = next(x for x in remote_clips() if x["file"] == sys.argv[2])
        plan = load_plan()
        item = {"file": e["file"], "account": e.get("account") or 1, "video_url": e["video_url"],
                "caption": e["caption"], "campaign": e.get("campaign"), "mood": e.get("mood"),
                "at": datetime.now().isoformat(),
                "status": "pending"}
        plan["items"].append(item)
        do_item(plan, item)
    else:
        run()


if __name__ == "__main__":
    main()
