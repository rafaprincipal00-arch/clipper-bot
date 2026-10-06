"""End-to-end run: source URL -> clips -> publish -> manifest.

    python -m clipper.pipeline --url <vod/video url> --creator "Name" --clips 3
    python -m clipper.pipeline --auto        # every enabled source in config/sources.json
"""
import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import highlights, publish, render

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUT = ROOT / "out"
MANIFEST = ROOT / "data" / "clips.json"
SEEN = ROOT / "data" / "seen.json"


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


def normalize_source(source: str) -> str:
    """Channel pages -> their VOD/upload listings so item 1 is the newest video."""
    s = source.split("?")[0].rstrip("/")
    if re.search(r"youtube\.com/(@[^/]+|c/[^/]+|channel/[^/]+)$", s):
        return s + "/videos"
    m = re.match(r"https?://(www\.)?twitch\.tv/([^/]+)$", s)
    if m:
        return f"https://www.twitch.tv/{m.group(2)}/videos?filter=archives&sort=time"
    return source


def kick_vods(channel: str) -> list[dict]:
    """yt-dlp's Kick extractor only handles live/VOD URLs, so list VODs via Kick's API."""
    import urllib.request
    req = urllib.request.Request(f"https://kick.com/api/v2/channels/{channel}/videos",
                                 headers={"User-Agent": "Mozilla/5.0 Chrome/130", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        vods = json.load(r)
    return [{"id": v["video"]["uuid"], "url": f"https://kick.com/{channel}/videos/{v['video']['uuid']}",
             "title": v.get("session_title", ""), "duration": (v.get("duration") or 0) / 1000,
             "views": v.get("views") or v["video"].get("views") or 0} for v in vods[:RECENT]]


RECENT = 8          # look at this many recent uploads per source
MIN_DURATION = 120  # skip shorts/teasers: nothing to cut from them


def recent_videos(source: str) -> list[dict]:
    """Recent uploads of a channel/VOD page with their view counts."""
    kick = re.match(r"https?://(www\.)?kick\.com/([^/?]+)/?$", source)
    if kick:
        return kick_vods(kick.group(2))
    raw = sh(["yt-dlp", "--no-warnings", "--flat-playlist", "--playlist-items", f"1-{RECENT}", "-J",
              normalize_source(source)])
    data = json.loads(raw)
    entries = data.get("entries") or [data]
    return [{"id": e["id"], "url": e.get("url") if str(e.get("url", "")).startswith("http") else e.get("webpage_url") or source,
             "title": e.get("title", ""), "duration": e.get("duration") or 0, "views": e.get("view_count") or 0}
            for e in entries if e.get("id")]


def best_video(source: str, seen: set[str]) -> dict | None:
    """The most-viewed recent upload not clipped yet: more views = proven interest = clips travel further."""
    vids = [v for v in recent_videos(source) if v["id"] not in seen and (not v["duration"] or v["duration"] >= MIN_DURATION)]
    return max(vids, key=lambda v: v["views"]) if vids else None


def most_replayed(url: str) -> list[tuple[float, float, float]]:
    """YouTube's 'most replayed' heatmap (start, end, intensity 0-1); empty for other platforms."""
    if "youtube.com" not in url and "youtu.be" not in url:
        return []
    try:
        info = json.loads(sh(["yt-dlp", "--no-warnings", "--skip-download", "-J", url]))
    except (subprocess.CalledProcessError, ValueError):
        return []
    return [(h["start_time"], h["end_time"], h["value"]) for h in info.get("heatmap") or []]


def latest_video(source: str) -> dict:
    """A direct video URL resolves to itself; a channel resolves to its newest upload."""
    vids = recent_videos(source)
    return vids[0]


def download_audio(url: str, dest: Path) -> Path:
    sh(["yt-dlp", "--no-warnings", "-f", "ba/b", "-x", "--audio-format", "m4a",
        "--audio-quality", "5", "-o", str(dest.with_suffix(".%(ext)s")), url])
    return dest.with_suffix(".m4a")


def download_section(url: str, start: float, end: float, dest: Path) -> Path:
    sh(["yt-dlp", "--no-warnings", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--download-sections", f"*{start:.0f}-{end:.0f}", "--force-keyframes-at-cuts",
        "--merge-output-format", "mp4", "-o", str(dest), url])
    return dest


def transcribe(audio: Path, offset: float, length: float) -> list[dict]:
    from faster_whisper import WhisperModel
    seg_file = audio.with_name(f"{audio.stem}_{int(offset)}.wav")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{offset}", "-t", f"{length}",
        "-i", str(audio), "-ac", "1", "-ar", "16000", str(seg_file)])
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(seg_file), word_timestamps=True, vad_filter=True)
    words = [{"word": w.word.strip(), "start": w.start + offset, "end": w.end + offset}
             for s in segments for w in (s.words or []) if w.word.strip()]
    seg_file.unlink(missing_ok=True)
    return words


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


def process(url: str, creator: str, clips: int, campaign: dict | None, do_publish: bool, min_score: int,
            vid: dict | None = None) -> list[dict]:
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    vid = vid or latest_video(url)
    print(f"Source: {vid['title']} ({vid['duration'] / 60:.0f} min, {vid.get('views', 0)} views) {vid['url']}")
    audio = download_audio(vid["url"], WORK / slug(vid["id"]))
    levels = highlights.loudness_per_second(str(audio))
    heat = most_replayed(vid["url"])
    if heat:
        print(f"  using YouTube most-replayed heatmap ({len(heat)} segments)")
    windows = highlights.peak_windows(levels, count=clips * 2, heat=heat)
    results = []
    for (w_start, w_end) in windows:
        if len(results) >= clips:
            break
        words = transcribe(audio, w_start, w_end - w_start)
        pick = highlights.pick_with_llm(words, creator) or highlights.fallback_pick(words, w_start, w_end)
        if not words:
            print(f"  skip {w_start}s: no speech")
            continue
        if pick.get("fallback") is None and pick["score"] < min_score:
            print(f"  skip {w_start}s: score {pick['score']}")
            continue
        start, end = float(pick["start"]), float(pick["end"])
        name = f"{slug(creator)}-{vid['id']}-{int(start)}"
        raw = download_section(vid["url"], start - 1, end + 1, WORK / f"{name}_raw.mp4")
        ass = WORK / f"{name}.ass"
        shifted = [{**w, "start": w["start"] - (start - 1), "end": w["end"] - (start - 1)} for w in words]
        render.write_ass(shifted, 1, 1 + end - start, pick["hook"], ass)
        final = OUT / f"{name}.mp4"
        render.render_vertical(str(raw), 1, 1 + end - start, ass, final, credit=campaign.get("credit", "") if campaign else "")
        tags = " ".join(f"#{t.lstrip('#')}" for t in campaign.get("hashtags", [])) if campaign else ""
        # CC BY music must be credited in the post text.
        caption = f"{pick['title']} {tags}\n{render.MUSIC_CREDIT}".strip()
        entry = {"file": final.name, "creator": creator, "source": vid["url"], "start": start, "end": end,
                 "score": pick["score"], "hook": pick["hook"], "caption": caption,
                 "campaign": campaign.get("campaign_url") if campaign else None,
                 "created": datetime.now(timezone.utc).isoformat(), "posts": {}}
        public_url = public_url_for(final)  # also feeds the panel's mp4 links
        if do_publish:
            entry["posts"] = publish.publish_all(final, pick["title"], caption, public_url)
        results.append(entry)
        print(f"  clip {final.name}  score={pick['score']}  {pick['hook']}")
    return results


def save(entries: list[dict]) -> None:
    MANIFEST.parent.mkdir(exist_ok=True)
    old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    MANIFEST.write_text(json.dumps(entries + old, indent=1, ensure_ascii=False), encoding="utf-8")


def run_auto(do_publish: bool, min_score: int, per_source: int) -> None:
    sources = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    budget_s = float(os.environ.get("RUN_BUDGET_MIN", "300")) * 60
    t0 = time.time()
    for src in [s for s in sources if s.get("enabled")]:
        if time.time() - t0 > budget_s:
            print("Run budget used up; remaining sources next run.")
            break
        try:
            vid = best_video(src["source"], seen)
        except subprocess.CalledProcessError as e:
            print(f"[{src['creator']}] cannot resolve source: {e.stderr[-300:] if e.stderr else e}")
            continue
        if not vid:
            print(f"[{src['creator']}] nothing new")
            continue
        print(f"[{src['creator']}] picked most-viewed new upload: {vid['title']} ({vid['views']} views)")
        try:
            save(process(vid["url"], src["creator"], per_source, src, do_publish, min_score, vid=vid))
            seen.add(vid["id"])
        except subprocess.CalledProcessError as e:
            print(f"[{src['creator']}] failed: {e.stderr[-500:] if e.stderr else e}")
        SEEN.write_text(json.dumps(sorted(seen)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--creator", default="creator")
    ap.add_argument("--clips", type=int, default=3)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--min-score", type=int, default=55)
    a = ap.parse_args()
    if a.auto:
        run_auto(a.publish, a.min_score, a.clips)
    elif a.url:
        save(process(a.url, a.creator, a.clips, None, a.publish, a.min_score))
    else:
        ap.error("--url or --auto")


if __name__ == "__main__":
    main()
