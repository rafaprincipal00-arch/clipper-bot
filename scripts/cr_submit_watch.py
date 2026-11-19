"""PC fallback for Content Rewards submissions while the CR_STATE secret is expired.

GitHub Actions (clipper/submit.py) pushes links it could not submit to data/cr_pending.json the moment the
submit fails. This loop polls that file (GitHub API, no git) and submits each link from the hidden bot
window in Rafa's Brave (his CR session, scripts/cr_submit_brave.py) inside CR's 30-minute window.

    python scripts/cr_submit_watch.py [--hours 24]        (Windows; idle work, ~1 API call / 2 min)
"""
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cr_submit_brave as sb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DONE = ROOT / "data" / "cr_watch_done.json"
LOG = ROOT / "data" / "cr_watch.log"
API = "https://api.github.com/repos/rafaprincipal00-arch/clipper-bot/contents/data/cr_pending.json?ref=main"
POLL_S = 120
WINDOW_MIN = 30


def log(*a: object) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(str(x) for x in a)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def pending() -> list[dict]:
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "clipper-bot"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(base64.b64decode(json.loads(r.read())["content"]) or b"[]")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


def main() -> None:
    hours = float(sys.argv[sys.argv.index("--hours") + 1]) if "--hours" in sys.argv else 24
    end = time.time() + hours * 3600
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    log(f"watch started ({hours} h)")
    while time.time() < end:
        try:
            items = pending()
        except Exception as e:  # noqa: BLE001 — network blips must not stop the loop
            log("cannot read cr_pending.json:", e)
            items = []
        now = datetime.now(timezone.utc)
        for it in items:
            if it["link"] in done:
                continue
            age = (now - datetime.fromisoformat(it["posted"])).total_seconds() / 60
            if age > WINDOW_MIN:
                log(f"too late ({age:.0f} min): {it['link']}")
                done.add(it["link"])
                continue
            try:
                res = sb.submit(it["campaign"], [it["link"]])
            except Exception as e:  # noqa: BLE001
                res = {"error": f"{type(e).__name__}: {e}"[:200]}
            log(f"{it['link']} -> {json.dumps(res)[:300]}")
            if not res.get("error") or age > WINDOW_MIN - 3:
                done.add(it["link"])  # errors are retried on the next poll while the window lasts
            DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
        time.sleep(POLL_S)
    log("watch finished")


if __name__ == "__main__":
    main()
