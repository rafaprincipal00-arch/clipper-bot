"""Windows logon trigger (Startup shortcut, runs hidden with pythonw).

First logon of each day (from ARM_FROM on) -> dispatches the GitHub workflow in batch mode:
9 different clips, accounts in turn (1, 2, 3, 1...), one every 8-9 min. That is the daily limit:
TikTok 3 per account (posted later from the PC) and YouTube 6 (the Google project's API quota, so the
first 6 clips also go to YouTube Shorts, 2 per channel).
Processing happens in GitHub Actions, so the PC only sends one HTTP request.
Log: data/logon_trigger.log (local only, gitignored).
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = "rafaprincipal00-arch/clipper-bot"
WORKFLOW = "clipper.yml"
BATCH = "9"
ARM_FROM = datetime(2026, 10, 7, 6, 0)  # never before the morning after it was set up
HERE = Path(__file__).resolve().parent.parent
STATE = HERE / "data" / "logon_trigger_state.json"
LOG = HERE / "data" / "logon_trigger.log"
NO_WINDOW = 0x08000000


def log(*a: object) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(map(str, a)) + "\n")


def github_token() -> str:
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60).stdout
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
    subprocess.Popen([sys.executable, str(HERE / "scripts" / "tiktok_poster.py"), "run"], cwd=str(HERE),
                     creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("TikTok poster started")


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
    for attempt in range(20):  # network may not be up right after logon
        try:
            dispatch(github_token())
            STATE.write_text(json.dumps({"last_run": today, "at": now.isoformat(timespec="seconds")}), encoding="utf-8")
            log(f"workflow dispatched: batch={BATCH} (accounts in turn, every 8-9 min)")
            start_tiktok_poster()
            return
        except (OSError, RuntimeError, urllib.error.URLError, subprocess.SubprocessError) as e:
            log(f"attempt {attempt + 1} failed: {e}")
            time.sleep(30)
    log("gave up after 20 attempts")


if __name__ == "__main__":
    main()
