"""PC side of YouTube sources: download only the moment windows, gently, and hand them to the cloud run.

GitHub's runners get blocked by YouTube's bot check, so the daily run finds no moments for YouTube
sources (MPJ, Ryan Zofay, Stanley Meng). This script runs on the PC at logon, BEFORE the workflow is
dispatched: it lists each enabled YouTube source's most-replayed moments, downloads just those ~80 s
windows and uploads them to a DRAFT release named "prefetch" (drafts are invisible to the public; the
workflow reads them with its token, uses them and deletes them).

Laptop safety: the heavy work (transcription, AI edit, render) stays in the cloud. Here we only list
and download, at idle CPU priority, with ffmpeg limited to 2 threads, waiting while the CPU is busy
and skipping entirely on low battery.
Log: data/yt_prefetch.log.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clipper import moments  # noqa: E402

REPO = "rafaprincipal00-arch/clipper-bot"
WORK = ROOT / "work" / "prefetch"
LOG = ROOT / "data" / "yt_prefetch.log"
PER_SOURCE = int(os.environ.get("PREFETCH_PER_SOURCE", "2"))
BUSY_CPU = 70  # % — wait while the user is using the machine hard
MIN_BATTERY = 30  # % — on battery below this, do nothing
NO_WINDOW = 0x08000000
IDLE = 0x00000040  # IDLE_PRIORITY_CLASS
FFMPEG = Path(sys.executable).parent / "ffmpeg.exe"


def log(*a: object) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(map(str, a))
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def github_token() -> str:
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60).stdout
    return next(x.split("=", 1)[1] for x in out.splitlines() if x.startswith("password="))


def api(path: str, body: bytes | None = None, method: str | None = None, base: str = "https://api.github.com",
        ctype: str = "application/json") -> bytes:
    req = urllib.request.Request(f"{base}/repos/{REPO}/{path}", data=body, method=method,
                                 headers={"Authorization": f"Bearer {github_token()}", "Content-Type": ctype,
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def remote_json(path: str, default):
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/{path}",
                                     headers={"Authorization": f"Bearer {github_token()}",
                                              "Accept": "application/vnd.github.raw"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except OSError:
        return default


def be_gentle() -> bool:
    """Idle priority for us and every child; False when we should not run at all."""
    me = psutil.Process()
    me.nice(psutil.IDLE_PRIORITY_CLASS)
    bat = psutil.sensors_battery()
    if bat and not bat.power_plugged and bat.percent < MIN_BATTERY:
        log(f"on battery at {bat.percent}% - skipping prefetch")
        return False
    return True


def wait_for_idle(max_wait_s: int = 900) -> None:
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        load = psutil.cpu_percent(interval=5)
        if load < BUSY_CPU:
            return
        log(f"CPU at {load:.0f}% - waiting before the next download")
        time.sleep(25)


def download(m: dict, dest: Path) -> bool:
    wait_for_idle()
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-progress",
           "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
           "--download-sections", f"*{max(0, m['start']):.0f}-{m['end']:.0f}",
           "--merge-output-format", "mp4", "--limit-rate", "8M",
           "--downloader-args", "ffmpeg:-threads 2", "--postprocessor-args", "ffmpeg:-threads 2",
           "-o", str(dest), m["url"]]
    if FFMPEG.exists():
        cmd[3:3] = ["--ffmpeg-location", str(FFMPEG)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=NO_WINDOW | IDLE, timeout=900)
    if r.returncode != 0 or not dest.exists():
        log(f"  download failed {m['id']}: {(r.stderr or '')[-300:]}")
        return False
    return True


def draft_release() -> dict:
    rels: list[dict] = json.loads(api("releases?per_page=30"))
    for rel in rels:
        if rel.get("draft") and rel.get("name") == "prefetch":
            return rel
    return json.loads(api("releases", json.dumps({"tag_name": "prefetch", "name": "prefetch", "draft": True,
                                       "body": "Moment windows downloaded on the PC; consumed and deleted by "
                                               "the clipper run."}).encode(), "POST"))


def upload(rel: dict, path: Path, ctype: str) -> None:
    for a in rel.get("assets", []):
        if a["name"] == path.name:
            api(f"releases/assets/{a['id']}", method="DELETE")
    api(f"releases/{rel['id']}/assets?name={path.name}", path.read_bytes(), "POST",
        base="https://uploads.github.com", ctype=ctype)


def main() -> None:
    if not be_gentle():
        return
    sources = [s for s in remote_json("config/sources.json", [])
               if s.get("enabled") and "youtube.com" in (s.get("source") or "")]
    seen = set(remote_json("data/seen.json", []))
    rel = draft_release()
    manifest = []
    for a in rel.get("assets", []):  # keep what the last run did not consume yet
        if a["name"] == "prefetch.json":
            req = urllib.request.Request(a["url"], headers={"Authorization": f"Bearer {github_token()}",
                                                            "Accept": "application/octet-stream"})
            try:
                manifest = json.loads(urllib.request.urlopen(req, timeout=60).read())
            except OSError:
                manifest = []
    have = {e["moment"]["id"] for e in manifest}
    WORK.mkdir(parents=True, exist_ok=True)
    for src in sources:
        try:
            found = [m for m in moments.strongest(moments.moments_for(src["source"]))
                     if m["id"] not in seen and m["id"] not in have]
        except (OSError, ValueError, subprocess.CalledProcessError) as e:
            log(f"[{src['creator']}] cannot list moments: {e}")
            continue
        log(f"[{src['creator']}] {len(found)} new moments")
        for m in found[:PER_SOURCE]:
            name = f"{m['id']}.mp4"
            dest = WORK / name
            if not download(m, dest):
                continue
            upload(rel, dest, "video/mp4")
            dest.unlink(missing_ok=True)
            manifest.append({"creator": src["creator"], "asset": name, "moment": m})
            log(f"  uploaded {name} ({m['title'][:50]})")
    mf = WORK / "prefetch.json"
    mf.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    upload(draft_release(), mf, "application/json")
    log(f"prefetch ready: {len(manifest)} moment windows")


if __name__ == "__main__":
    main()
