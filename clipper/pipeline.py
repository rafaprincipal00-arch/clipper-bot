"""End-to-end run: viral moment -> short multi-cut edit -> publish -> campaign submit -> manifest.

    python -m clipper.pipeline --auto                 # next best moment of every enabled source
    python -m clipper.pipeline --url <vod/clip url> --start 1200 --end 1290 --creator "Name"

Only the moment's window (~1-2 min) is downloaded, never the whole VOD; the raw window and every
intermediate file are deleted as soon as the clip is rendered (see `scratch`).
"""
import argparse
import json
import os
import random
import re
import shutil
import subprocess
import time
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from . import highlights, layout, moments, publish, render, submit

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUT = ROOT / "out"
MANIFEST = ROOT / "data" / "clips.json"
SEEN = ROOT / "data" / "seen.json"
KEEP_FINAL_HOURS = float(os.environ.get("KEEP_FINAL_HOURS", "24"))
CLIP_GAP_MIN = float(os.environ.get("CLIP_GAP_MIN", "6"))  # one clip every 5-8 min
# YouTube Data API: 10,000 units/day and an upload costs 1,600 -> 6 uploads/day per project.
DAILY_CAP = {"youtube": int(os.environ.get("YT_DAILY_MAX", "6")),
             "tiktok": int(os.environ.get("TIKTOK_DAILY_MAX", "12")),
             "instagram": int(os.environ.get("IG_DAILY_MAX", "25"))}


def capped_platforms() -> set[str]:
    """Platforms that already got their daily maximum of successful posts today. "Today" is the YouTube
    quota day, which resets at midnight Pacific time (09:00 in Spain)."""
    if not MANIFEST.exists():
        return set()
    since = datetime.now(ZoneInfo("America/Los_Angeles")).replace(hour=0, minute=0, second=0).timestamp()
    counts = dict.fromkeys(DAILY_CAP, 0)
    for e in json.loads(MANIFEST.read_text(encoding="utf-8")):
        if datetime.fromisoformat(e["created"]).timestamp() < since:
            continue
        for k, v in (e.get("posts") or {}).items():
            if k in counts and isinstance(v, str) and not v.startswith(("error", "skipped")):
                counts[k] += 1
    return {k for k, n in counts.items() if n >= DAILY_CAP[k]}


def working_platforms() -> set[str]:
    """Platforms that posted successfully in the last 3 days (YouTube assumed if none yet).
    Clips are only worth making while at least one of these still has daily room."""
    ok = set()
    if MANIFEST.exists():
        since = datetime.now(timezone.utc).timestamp() - 3 * 86400
        for e in json.loads(MANIFEST.read_text(encoding="utf-8")):
            if datetime.fromisoformat(e["created"]).timestamp() >= since:
                ok |= {k for k, v in (e.get("posts") or {}).items()
                       if k in DAILY_CAP and isinstance(v, str) and not v.startswith(("error", "skipped"))}
    return ok or {"youtube"}


def sh(cmd: list[str]) -> str:
    if cmd[0] == "yt-dlp" and os.environ.get("YTDLP_COOKIES"):
        # Netscape cookies.txt from a throwaway YouTube account; YouTube blocks datacenter IPs without it.
        jar = WORK / "cookies.txt"
        WORK.mkdir(exist_ok=True)
        jar.write_text(os.environ["YTDLP_COOKIES"], encoding="utf-8")
        cmd = [cmd[0], "--cookies", str(jar), *cmd[1:]]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if p.returncode != 0:
        print(f"  $ {' '.join(cmd[:3])}... failed:\n{p.stderr[-1200:]}")
        raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)
    return p.stdout


@contextmanager
def scratch(name: str):
    """Per-clip work dir that is ALWAYS deleted (success or failure): the raw, unedited window never stays on disk."""
    d = WORK / name
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def prune_outputs(max_age_h: float = KEEP_FINAL_HOURS) -> None:
    """Rendered clips are already on the platforms + GitHub release; keep only the last day locally."""
    if not OUT.exists():
        return
    cutoff = time.time() - max_age_h * 3600
    for f in OUT.glob("*.mp4"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def download_window(url: str, start: float, end: float, dest: Path) -> Path:
    """Just the moment's window. Clip URLs (Kick HLS / Twitch clip) are short already: take them whole."""
    sec = [] if start <= 0 and end <= 75 else ["--download-sections", f"*{start:.0f}-{end:.0f}"]
    sh(["yt-dlp", "--no-warnings", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", *sec,
        "--merge-output-format", "mp4", "-o", str(dest), url])
    return dest


def transcribe(media: Path) -> list[dict]:
    from faster_whisper import WhisperModel
    wav = media.with_suffix(".wav")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(wav), word_timestamps=True, vad_filter=True)
    words = [{"word": w.word.strip(), "start": w.start, "end": w.end}
             for s in segments for w in (s.words or []) if w.word.strip()]
    wav.unlink(missing_ok=True)
    return words


def duration(media: Path) -> float:
    out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(media)])
    return float(out.strip() or 0)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "clip"


def public_url_for(path: Path) -> str | None:
    """Instagram pulls video from a public URL: attach the clip to a GitHub release."""
    repo, tag = os.environ.get("GITHUB_REPOSITORY"), "clips"
    if not repo or not os.environ.get("GH_TOKEN"):
        return None
    if subprocess.run(["gh", "release", "view", tag, "-R", repo], capture_output=True).returncode != 0:
        subprocess.run(["gh", "release", "create", tag, "-R", repo, "-t", "Rendered clips", "-n", "Auto"], check=True)
    subprocess.run(["gh", "release", "upload", tag, str(path), "--clobber", "-R", repo], check=True)
    return f"https://github.com/{repo}/releases/download/{tag}/{path.name}"


def make_clip(moment: dict, creator: str, campaign: dict | None, do_publish: bool, min_score: int,
              account: int | None = None) -> dict | None:
    """One moment -> one published clip. Returns the manifest entry or None if skipped."""
    t0 = time.time()
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    name = f"{slug(creator)}-{slug(moment['id'])}"
    with scratch(name) as d:
        raw = download_window(moment["url"], moment["start"], moment["end"], d / "raw.mp4")
        t_dl = time.time()
        words = transcribe(raw)
        length = duration(raw)
        if not words:
            print(f"  skip {moment['id']}: no speech")
            return None
        edit = (highlights.pick_edit(words, creator, moment["title"], 0, length)
                or highlights.fallback_edit(words, 0, length))
        if not edit.get("fallback") and edit["score"] < min_score:
            print(f"  skip {moment['id']}: score {edit['score']}")
            return None
        segs = highlights.micro_cut(edit["segments"], words)
        if highlights.total(segs) < highlights.MIN_TOTAL:
            # micro-cuts removed pauses: top up with more surrounding context, then cut that too.
            # Added phrases are already pause-free; words=[] keeps silent run-ons and only splits into ~3 s beats.
            segs = highlights.micro_cut(highlights.pad_to_min(segs, words, 0, length), [])
        if highlights.total(segs) < highlights.MIN_TOTAL - 0.5:
            print(f"  skip {moment['id']}: only {highlights.total(segs):.1f}s of material (min {highlights.MIN_TOTAL:.0f}s)")
            return None
        info = layout.analyse(str(raw), min(s for s, _ in segs), max(e for _, e in segs))
        # A/B test: alternate blurred-horizontal and full-vertical framing (stable per clip name).
        style = "blur" if zlib.crc32(name.encode()) % 2 else "vertical"
        mood = edit.get("mood") if edit.get("mood") in render.MOODS else "funny"
        ass = d / "captions.ass"
        render.write_ass(render.remap_words(words, segs), 0, sum(e - s for s, e in segs), edit["hook"], ass)
        final = OUT / f"{name}.mp4"
        render.render_edit(str(raw), segs, info, ass, final, credit=(campaign or {}).get("credit", ""),
                           mood=mood, style=style)
    # scratch dir (raw window, wav, captions) is gone here; only the edited clip remains.
    t_render = time.time()
    tags = " ".join(f"#{t.lstrip('#')}" for t in (campaign or {}).get("hashtags", []))
    caption = f"{edit['title']} {tags}\n{render.MUSIC_CREDIT}".strip()  # CC BY music must be credited
    entry = {"file": final.name, "creator": creator, "source": moment["url"], "start": moment["start"] + segs[0][0],
             "end": moment["start"] + segs[-1][1], "cuts": len(segs), "length": round(sum(e - s for s, e in segs), 1),
             "layout": info["kind"], "style": style, "mood": mood, "signal": moment["signal"], "score": edit["score"], "hook": edit["hook"],
             "caption": caption, "title": edit["title"], "campaign": (campaign or {}).get("campaign_url"),
             "created": datetime.now(timezone.utc).isoformat(), "posts": {}}
    public_url = public_url_for(final)  # also feeds the panel's mp4 links
    entry["video_url"] = public_url  # the PC TikTok poster downloads the clip from here
    if do_publish:
        entry["posts"] = publish.publish_all(final, edit["title"], caption, public_url, skip=capped_platforms(),
                                             account=account)
        if account is not None:
            entry["account"] = account + 1
        links = [v for v in entry["posts"].values() if isinstance(v, str) and v.startswith("https://")]
        if links and entry["campaign"]:
            # Content Rewards only accepts links posted <30 min ago, so submit right away.
            try:
                entry["submission"] = submit.submit(entry["campaign"], links)
            except Exception as e:  # never lose the publish record over a submit failure
                entry["submission"] = {"error": str(e)[:300]}
            print(f"  submit: {entry['submission']}")
    entry["timing_s"] = {"download": round(t_dl - t0), "transcribe+edit+render": round(t_render - t_dl),
                         "publish+submit": round(time.time() - t_render), "total": round(time.time() - t0)}
    print(f"  clip {final.name}  {entry['length']}s/{entry['cuts']} cuts/{style}/{info['kind']}/{mood}  score={edit['score']}"
          f"  {edit['hook']}  timing={entry['timing_s']}")
    return entry


def save(entries: list[dict]) -> None:
    MANIFEST.parent.mkdir(exist_ok=True)
    old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    MANIFEST.write_text(json.dumps(entries + old, indent=1, ensure_ascii=False), encoding="utf-8")


ACCOUNTS = int(os.environ.get("ACCOUNTS", "3"))  # YouTube channels / TikTok accounts, used in turn


def gap_seconds() -> float:
    """CLIP_GAP_MIN, or a random gap inside CLIP_GAP_MAX_MIN when set (e.g. 8-9 min looks less robotic)."""
    lo = CLIP_GAP_MIN
    hi = float(os.environ.get("CLIP_GAP_MAX_MIN") or lo)
    return random.uniform(lo, max(lo, hi)) * 60


def run_auto(do_publish: bool, min_score: int, per_source: int, total: int = 0, per_account: bool = False) -> None:
    """Round-robin over sources, best unseen moment each, paced to one clip every CLIP_GAP_MIN minutes
    until the run budget ends (the next scheduled run carries on).
    total > 0 stops after that many clips; per_account sends the clips to the accounts in turn
    (1, 2, 3, 1, 2, 3...). A platform at its daily cap is skipped, the others keep getting clips."""
    sources = [s for s in json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8")) if s.get("enabled")]
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    budget_s = float(os.environ.get("RUN_BUDGET_MIN", "300")) * 60
    t0 = time.time()
    prune_outputs()
    queues: dict[str, list[dict]] = {}
    for src in sources:
        try:
            queues[src["creator"]] = [m for m in moments.strongest(moments.moments_for(src["source"]))
                                      if m["id"] not in seen]
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
            print(f"[{src['creator']}] cannot list moments: {e}")
            queues[src["creator"]] = []
        print(f"[{src['creator']}] {len(queues[src['creator']])} new moments")
    made = dict.fromkeys(queues, 0)
    done = 0
    last_clip = 0.0
    next_gap = gap_seconds()
    while time.time() - t0 < budget_s:
        progressed = False
        for src in sources:
            q = queues[src["creator"]]
            if total and done >= total:
                print(f"Done: {done} clips.")
                return
            if not q or made[src["creator"]] >= per_source or time.time() - t0 > budget_s:
                continue
            if do_publish and capped_platforms() >= working_platforms():
                print("Every working platform hit its daily cap; stopping.")
                return
            wait = next_gap - (time.time() - last_clip)
            if do_publish and last_clip and wait > 0:
                print(f"  next clip in {wait / 60:.1f} min")
                time.sleep(wait)
            m = q.pop(0)
            progressed = True
            print(f"[{src['creator']}] {m['signal']} {m['views']} views: {m['title'][:60]}")
            seen.add(m["id"])  # mark even on failure so a broken moment is not retried forever
            try:
                entry = make_clip(m, src["creator"], src, do_publish, min_score,
                                  account=done % ACCOUNTS if per_account else None)
            except subprocess.CalledProcessError as e:
                print(f"  failed: {(e.stderr or str(e))[-400:]}")
                entry = None
            SEEN.write_text(json.dumps(sorted(seen)))
            if entry:
                save([entry])
                made[src["creator"]] += 1
                done += 1
                last_clip = time.time()
                next_gap = gap_seconds()
        if not progressed:
            print(f"No moments left this run ({done} clips made).")
            return


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float, default=0)
    ap.add_argument("--creator", default="creator")
    ap.add_argument("--clips", type=int, default=1, help="clips per source per run")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--min-score", type=int, default=70)
    ap.add_argument("--total", type=int, default=0, help="stop after this many clips (0 = no limit)")
    ap.add_argument("--per-account", action="store_true", help="clip N goes to account N (YT channel + TikTok)")
    a = ap.parse_args()
    if a.auto:
        run_auto(a.publish, a.min_score, a.clips, a.total, a.per_account)
    elif a.url:
        m = {"id": f"manual-{int(time.time())}", "url": a.url, "start": a.start, "end": a.end or a.start + 90,
             "views": 0, "title": "", "signal": "manual"}
        entry = make_clip(m, a.creator, None, a.publish, a.min_score)
        if entry:
            save([entry])
    else:
        ap.error("--url or --auto")


if __name__ == "__main__":
    main()
