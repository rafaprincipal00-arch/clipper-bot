"""Daily trigger, started by the Hermes cron job clipper-daily-batch (autopilot.py daily) on the Linux server.
(Name kept from the old Windows logon shortcut.)

First call of each day (from ARM_FROM on) -> dispatches the GitHub workflow in batch mode:
15 different clips (5 per TikTok account), accounts in turn (1, 2, 3, 1...), one every 8-9 min. That is the daily limit:
TikTok 3 per account (posted later from the PC) and YouTube 6 (the Google project's API quota, so the
first 6 clips also go to YouTube Shorts, 2 per channel).
Processing happens in GitHub Actions. Before dispatching, the PC downloads the YouTube moment windows that
GitHub's runners cannot fetch (scripts/yt_prefetch.py: idle priority, waits while the CPU is busy, skips on
low battery, at most PREFETCH_MAX_MIN minutes so the daily run is never held back for long).
Log: data/logon_trigger.log (local only, gitignored).
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = "rafaprincipal00-arch/clipper-bot"
WORKFLOW = "clipper.yml"
BATCH = "15"
ARM_FROM = datetime(2026, 10, 7, 6, 0)  # never before the morning after it was set up
HERE = Path(__file__).resolve().parent.parent
STATE = HERE / "data" / "logon_trigger_state.json"
LOG = HERE / "data" / "logon_trigger.log"
PREFETCH_MAX_MIN = 25


def log(*a: object) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(map(str, a)) + "\n")


def github_token() -> str:
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, timeout=60).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("no GitHub credential stored in git")


def dispatch(token: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
        data=json.dumps({"ref": "main", "inputs": {"batch": BATCH, "publish": True}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 204:
            raise RuntimeError(f"GitHub answered {r.status}")


def start_tiktok_poster() -> None:
    """Hidden daemon that posts today's clips to TikTok at staggered times (scripts/tiktok_poster.py)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}  # see tiktok_poster
    subprocess.Popen([sys.executable, str(HERE / "scripts" / "tiktok_poster.py"), "run"], cwd=str(HERE), env=env,
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("TikTok poster started")


def prefetch_youtube() -> None:
    """Download YouTube moment windows on the PC for the cloud run; never blocks the day's run for long."""
    try:
        r = subprocess.run([sys.executable, str(HERE / "scripts" / "yt_prefetch.py")], cwd=str(HERE),
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=PREFETCH_MAX_MIN * 60)
        log(f"YouTube prefetch finished (exit {r.returncode}, details in data/yt_prefetch.log)")
    except subprocess.TimeoutExpired:
        log(f"YouTube prefetch stopped after {PREFETCH_MAX_MIN} min; dispatching with what is uploaded")


def main() -> None:
    now = datetime.now()
    if now < ARM_FROM:
        log("logon before", ARM_FROM, "- not armed yet")
        return
    today = now.date().isoformat()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if state.get("last_run") == today and "--force" not in sys.argv:
        log("already launched today")
        return
    prefetch_youtube()
    for attempt in range(20):  # network may not be up right after logon
        try:
            dispatch(github_token())
            STATE.write_text(json.dumps({"last_run": today, "at": now.isoformat(timespec="seconds")}), encoding="utf-8")
            log(f"workflow dispatched: batch={BATCH} (accounts in turn, every 8-9 min)")
            start_tiktok_poster()  # headless, own browser (scripts/tiktok_bg.py)
            return
        except (OSError, RuntimeError, urllib.error.URLError, subprocess.SubprocessError) as e:
            log(f"attempt {attempt + 1} failed: {e}")
            time.sleep(30)
    log("gave up after 20 attempts")


if __name__ == "__main__":
    main()
