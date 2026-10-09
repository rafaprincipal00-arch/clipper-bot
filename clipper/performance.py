"""Learn from our own posts: YouTube views per clip → which creators and hooks work on our channels.

`refresh()` reads public statistics of every Short in data/clips.json (YouTube Data API, one call per 50
videos, ~1 quota unit; yt-dlp per video when the token lacks the read scope) and writes data/performance.json. `notes()` turns it into a short block that
highlights.py adds to the Gemini prompt, and `source_order()` lets the pipeline give the best creators
more clips. Clips younger than 24 h are ignored: their views are not settled yet.
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "clips.json"
PERF = ROOT / "data" / "performance.json"
MIN_AGE = timedelta(hours=24)


def _token() -> str | None:
    cid, secret, refresh = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if not (cid and secret and refresh):
        return None
    body = urllib.parse.urlencode({"client_id": cid, "client_secret": secret, "refresh_token": refresh,
                                   "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=30) as r:
        return json.load(r)["access_token"]


def _yt_id(url: str) -> str | None:
    m = re.search(r"shorts/([\w-]{11})", url or "")
    return m.group(1) if m else None


def _api_stats(ids: list[str]) -> dict[str, dict]:
    tok = _token()
    if not tok:
        raise RuntimeError("no YouTube credentials")
    stats: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        req = urllib.request.Request("https://www.googleapis.com/youtube/v3/videos?part=statistics&id="
                                     + ",".join(ids[i:i + 50]), headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            for it in json.load(r).get("items", []):
                stats[it["id"]] = it["statistics"]
    return stats


def _ytdlp_stats(ids: list[str]) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for vid in ids:
        r = subprocess.run([sys.executable, "-m", "yt_dlp", "-J", "--skip-download", "--no-warnings",
                            f"https://www.youtube.com/shorts/{vid}"], capture_output=True, text=True,
                           encoding="utf-8", timeout=120)
        if r.returncode == 0:
            j = json.loads(r.stdout)
            stats[vid] = {"viewCount": j.get("view_count") or 0, "likeCount": j.get("like_count") or 0}
    return stats


def refresh() -> dict | None:
    if not MANIFEST.exists():
        return None
    clips = json.loads(MANIFEST.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    rows = [(c, _yt_id((c.get("posts") or {}).get("youtube", ""))) for c in clips]
    rows = [(c, v) for c, v in rows if v and now - datetime.fromisoformat(c["created"]) >= MIN_AGE]
    ids = [v for _, v in rows]
    if not ids:
        return None
    try:
        stats = _api_stats(ids)
    except Exception as e:  # noqa: BLE001 — upload-only token or no creds: public stats via yt-dlp
        print(f"  performance: API unavailable ({str(e)[:80]}), using yt-dlp")
        stats = _ytdlp_stats(ids)
    if not stats:
        return None
    posts = []
    for c, vid in rows:
        s = stats.get(vid)
        if s:
            posts.append({"creator": c["creator"], "hook": c.get("hook"), "title": c.get("title"),
                          "mood": c.get("mood"), "hook_type": c.get("hook_type"), "score": c.get("score"),
                          "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)), "id": vid})
    by_creator: dict[str, dict] = {}
    for p in posts:
        b = by_creator.setdefault(p["creator"], {"clips": 0, "views": 0})
        b["clips"] += 1
        b["views"] += p["views"]
    for b in by_creator.values():
        b["avg_views"] = round(b["views"] / b["clips"])
    posts.sort(key=lambda p: -p["views"])
    data = {"updated": now.isoformat(timespec="seconds"), "clips": len(posts), "by_creator": by_creator,
            "top": posts[:8], "bottom": [p for p in posts if p["views"] < 20][-8:]}
    PERF.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def load() -> dict | None:
    return json.loads(PERF.read_text(encoding="utf-8")) if PERF.exists() else None


def notes(creator: str) -> str:
    """Prompt block: what got views on OUR channels, so the editor copies winners and avoids losers."""
    d = load()
    if not d or not d.get("top"):
        return ""
    lines = [f"What worked on our own channels so far ({d['clips']} Shorts with settled views):"]
    lines += [f"- {p['views']} views: {p['creator']} · \"{p['hook']}\" ({p['mood']})" for p in d["top"][:6]]
    if d.get("bottom"):
        lines.append("Flops (under 20 views), do not repeat this kind of moment:")
        lines += [f"- {p['views']} views: {p['creator']} · \"{p['hook']}\"" for p in d["bottom"][:6]]
    c = d["by_creator"].get(creator)
    if c:
        best = max(v["avg_views"] for v in d["by_creator"].values()) or 1
        lines.append(f"{creator} averages {c['avg_views']} views per clip on our channels "
                     f"(best creator averages {best}).")
    return "\n".join(lines)


def source_order(sources: list[dict]) -> list[dict]:
    """Best average views first; creators with no settled data yet sit between the best and the worst."""
    d = load() or {}
    avg = {k: v["avg_views"] for k, v in (d.get("by_creator") or {}).items() if v["clips"] >= 2}
    mid = (min(avg.values()) + max(avg.values())) / 2 if avg else 0
    return sorted(sources, key=lambda s: -avg.get(s["creator"], mid))
