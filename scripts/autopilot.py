"""Keeps the clipper running on its own; run by the Hermes cron jobs of the "clipper" profile.

    python scripts/autopilot.py daily    # make sure today's batch is launched (same path as the logon trigger)
    python scripts/autopilot.py watch    # failed clipper run today -> relaunch (max 2) ; poster failures -> alert
    python scripts/autopilot.py money    # run cr_earnings.yml, alert on any change in earnings / approvals
    python scripts/autopilot.py digest   # what got published today + real views of the best clips
    python scripts/autopilot.py notify "text"

Telegram is the only output channel, and only for: something published, errors, money. Everything heavy runs in
GitHub Actions; on the PC this only starts the existing idle-priority helpers (logon trigger, TikTok poster).
State: data/autopilot_state.json, log: data/autopilot.log (both local only).
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import tiktok_poster as tp  # noqa: E402  (GitHub token + API helper)

STATE = ROOT / "data" / "autopilot_state.json"
LOG = ROOT / "data" / "autopilot.log"
TRIGGER_STATE = ROOT / "data" / "logon_trigger_state.json"
POSTER_LOG = ROOT / "data" / "tiktok_poster.log"
HERMES_ENV = Path.home() / "AppData" / "Local" / "hermes" / ".env"  # Telegram bot of the main Hermes profile
TOP_CLIPS = (Path.home() / "AppData/Local/hermes/profiles/clipper/skills/clipper/clipper-ops/scripts/top_clips.py")
NO_WINDOW, IDLE = 0x08000000, 0x00000040
MAX_RETRIES = 2
PYW = Path(sys.executable).with_name("pythonw.exe")


def log(*a: object) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(map(str, a))
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")


# ---------------- Telegram ----------------
def _env(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    for line in HERMES_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(f"{key} not configured")


def notify(text: str) -> None:
    token, chat = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_HOME_CHANNEL").split(":")[0]
    data = urllib.parse.urlencode({"chat_id": chat, "text": ("🎬 Clipper\n" + text)[:4000],
                                   "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=30) as r:
        ok = json.loads(r.read()).get("ok")
    log("telegram sent" if ok else "telegram NOT sent", "|", text.splitlines()[0][:80])


def alert_once(state: dict, key: str, text: str) -> None:
    """Errors are sent once per key, so a broken thing does not ping every 30 min."""
    sent = state.setdefault("alerts", {})
    if key not in sent:
        notify("⚠️ " + text)
        sent[key] = datetime.now().isoformat(timespec="seconds")


# ---------------- GitHub ----------------
def runs_today(workflow: str) -> list[dict]:
    runs = tp.gh(f"actions/workflows/{workflow}/runs?per_page=20")["workflow_runs"]
    today = datetime.now().date()
    return [r for r in runs if datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).astimezone().date() == today]


def dispatch(workflow: str, inputs: dict) -> None:
    tp.gh(f"actions/workflows/{workflow}/dispatches", {"ref": "main", "inputs": inputs})
    log("dispatched", workflow, inputs)


def failed_step(run: dict) -> str:
    try:
        for job in tp.gh(f"actions/runs/{run['id']}/jobs")["jobs"]:
            for st in job.get("steps", []):
                if st.get("conclusion") == "failure":
                    return st["name"]
    except Exception:  # noqa: BLE001
        pass
    return "?"


def job_log(run: dict) -> str:
    job = tp.gh(f"actions/runs/{run['id']}/jobs")["jobs"][0]

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    req = urllib.request.Request(f"https://api.github.com/repos/{tp.REPO}/actions/jobs/{job['id']}/logs",
                                 headers={"Authorization": f"Bearer {tp.github_token()}"})
    try:  # the storage redirect rejects the GitHub auth header: follow it without
        urllib.request.build_opener(NoRedirect).open(req)
        return ""
    except urllib.error.HTTPError as e:
        return urllib.request.urlopen(e.headers["Location"], timeout=60).read().decode("utf-8", "ignore")


# ---------------- PC helpers ----------------
def running(script: str) -> bool:
    import psutil
    for p in psutil.process_iter(["cmdline"]):
        try:
            if any(script in (c or "") for c in (p.info["cmdline"] or [])):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def start(script: str, *args: str) -> None:
    exe = PYW if PYW.exists() else Path(sys.executable)
    subprocess.Popen([str(exe), str(ROOT / "scripts" / script), *args], cwd=str(ROOT),
                     creationflags=NO_WINDOW | IDLE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("started", script, *args)


def launched_today() -> bool:
    s = json.loads(TRIGGER_STATE.read_text(encoding="utf-8")) if TRIGGER_STATE.exists() else {}
    return s.get("last_run") == datetime.now().date().isoformat()


# ---------------- commands ----------------
def cmd_daily() -> None:
    """Safety net for days without a fresh Windows logon: same idempotent path as the Startup shortcut."""
    if launched_today() or running("logon_trigger.pyw"):
        log("daily: batch already launched today")
        return
    start("logon_trigger.pyw")  # prefetch (idle, capped 25 min) -> dispatch batch -> TikTok poster


def cmd_watch() -> None:
    state = load_state()
    today = datetime.now().date().isoformat()
    if state.get("day") != today:
        state.update(day=today, retries=0, alerts={})
    try:
        runs = runs_today("clipper.yml")
    except Exception as e:  # noqa: BLE001
        log("watch: GitHub unreachable:", e)
        runs = None
    if runs and launched_today():
        last = runs[0]
        if last["status"] == "completed" and last["conclusion"] in ("failure", "timed_out", "startup_failure"):
            step = failed_step(last)
            if state["retries"] < MAX_RETRIES:
                state["retries"] += 1
                dispatch("clipper.yml", {"batch": "15", "publish": "true"})
                if not running("tiktok_poster.py"):
                    start("tiktok_poster.py", "run")
                alert_once(state, f"run-{last['id']}",
                           f"El run de clips de hoy falló en «{step}» ({last['html_url']}). "
                           f"Relanzado automáticamente (intento {state['retries']}/{MAX_RETRIES}).")
            else:
                alert_once(state, f"run-{last['id']}",
                           f"El run de clips falló otra vez en «{step}» y ya van {MAX_RETRIES} reintentos: "
                           f"hoy no habrá más clips. {last['html_url']}")
    # The poster waits only 3 h for the day's clips (clips.json lands when the whole batch ends), so a late or
    # relaunched run can outlive it: bring it back while today's TikTok posts are still to be placed.
    if runs and launched_today() and datetime.now().hour < 23 and not running("tiktok_poster.py"):
        plan = json.loads(tp.PLAN.read_text(encoding="utf-8")) if tp.PLAN.exists() else {}
        items = plan.get("items", []) if plan.get("date") == today else []
        busy = runs[0]["status"] != "completed" or runs[0]["conclusion"] == "success"
        if busy and (len(items) < tp.EXPECTED or any(i["status"] == "pending" for i in items)):
            start("tiktok_poster.py", "run")
    # TikTok posts that failed for good today (the poster retries once by itself)
    if POSTER_LOG.exists():
        for line in POSTER_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(rf"{today} [\d:]+ FAILED (\S+) \(try 2\): (.*)", line)
            if m:
                alert_once(state, f"tt-{m.group(1)}", f"TikTok no pudo publicar {m.group(1)}: {m.group(2)[:200]}")
    save_state(state)


def cmd_money() -> None:
    state = load_state()
    before = {r["id"] for r in tp.gh("actions/workflows/cr_earnings.yml/runs?per_page=5")["workflow_runs"]}
    dispatch("cr_earnings.yml", {})
    run = None
    for _ in range(60):  # up to 30 min
        time.sleep(30)
        new = [r for r in tp.gh("actions/workflows/cr_earnings.yml/runs?per_page=5")["workflow_runs"]
               if r["id"] not in before]
        if new and new[0]["status"] == "completed":
            run = new[0]
            break
    today = datetime.now().date().isoformat()
    if not run:
        log("money: cr_earnings did not finish in 30 min")
        return
    text = job_log(run)
    m = re.search(r"CR_SUMMARY (.*)", text)
    if "CONTENT REWARDS DOWN" in text:
        log("money: Content Rewards is on its maintenance page; trying again tomorrow")
        return
    if run["conclusion"] != "success" or not m:
        err = re.search(r"(SESSION EXPIRED[^\n]*|earnings page not read|\w+Error: [^\n]{0,160})", text)
        state.setdefault("alerts", {})
        alert_once(state, f"money-{today}", f"No pude leer los cobros de Content Rewards: "
                   f"{err.group(1) if err else run['conclusion']} ({run['html_url']})")
        save_state(state)
        return
    now = dict(kv.split("=", 1) for kv in m.group(1).split())
    old = state.get("money")
    log("money:", now)
    changes = []
    if old:
        for k, label in (("lifetime", "Ganado total"), ("withdraw", "Disponible para retirar"),
                         ("approved", "Clips aprobados"), ("rejected", "Clips rechazados")):
            if k in now and now.get(k) != old.get(k):
                unit = "$" if k in ("lifetime", "withdraw") else ""
                changes.append(f"{label}: {unit}{old.get(k, '?')} → {unit}{now[k]}")
    elif float(now.get("lifetime", 0)) > 0:
        changes.append(f"Ganado total: ${now['lifetime']}, disponible ${now.get('withdraw', '?')}")
    if changes:
        notify("💰 Content Rewards\n" + "\n".join(changes) +
               f"\n(pendientes de revisión: {now.get('pending', '?')})")
    state["money"] = now
    save_state(state)


def cmd_digest() -> None:
    """Once a day, only if something was published today: the links, plus real views of the best clips."""
    today = datetime.now().date().isoformat()
    lines = []
    try:
        clips = tp.remote_clips()
    except Exception as e:  # noqa: BLE001
        log("digest: clips.json unreachable:", e)
        clips = []
    for e in clips:
        created = datetime.fromisoformat(e["created"]).astimezone().date().isoformat() if e.get("created") else ""
        yt = (e.get("posts") or {}).get("youtube")
        if created == today and isinstance(yt, str) and yt.startswith("http"):
            lines.append(f"YT · {e.get('creator')} · {yt}")
    if POSTER_LOG.exists():
        for line in POSTER_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(rf"{today} [\d:]+ posted (\S+?)\.mp4 -> (\S+)", line)
            if m:
                lines.append(f"TikTok · {m.group(1)[:30]} · {m.group(2)}")
    if not lines:
        log("digest: nothing published today")
        return
    subprocess.run([r"C:\Program Files\Git\cmd\git.exe", "-C", str(ROOT), "pull", "-q", "--autostash"],
                   creationflags=NO_WINDOW, timeout=120, capture_output=True)
    top = subprocess.run([sys.executable, str(TOP_CLIPS), "5"], capture_output=True, text=True,
                         timeout=900, creationflags=NO_WINDOW | IDLE).stdout.strip()
    notify(f"📤 Publicado hoy ({len(lines)}):\n" + "\n".join(lines[:20]) +
           (f"\n…y {len(lines) - 20} más" if len(lines) > 20 else "") +
           "\n\n👀 Vistas reales (top 5 de siempre):\n" + top)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "notify":
            notify(" ".join(sys.argv[2:]))
        elif cmd in ("daily", "watch", "money", "digest"):
            globals()[f"cmd_{cmd}"]()
        else:
            raise SystemExit(__doc__)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — one alert, never a crash loop
        log(f"{cmd} crashed: {type(e).__name__}: {e}")
        state = load_state()
        try:
            alert_once(state, f"crash-{cmd}-{datetime.now(timezone.utc):%Y%m%d}",
                       f"autopilot {cmd} falló: {type(e).__name__}: {str(e)[:200]}")
            save_state(state)
        except Exception as e2:  # noqa: BLE001
            log("cannot alert:", e2)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
