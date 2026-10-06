"""Find viral moments WITHOUT downloading whole VODs.

Signals, strongest first:
- Twitch / Kick viewer clips sorted by views: viewers already marked what was worth clipping.
- Twitch chat density (idea from hotclip's danmaku heat): where chat explodes, something happened.
- YouTube "most replayed" heatmap.
Each moment points at a short window of the source; only that window is downloaded later.
"""
import json
import re
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"
TWITCH_GQL = "https://gql.twitch.tv/gql"
TWITCH_WEB_CLIENT = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # public client id of twitch.tv itself
CONTEXT_BEFORE = 35  # seconds of lead-in fetched so the edit can keep the set-up
CONTEXT_AFTER = 25


def _get_json(url: str, data: dict | None = None, headers: dict | None = None) -> dict | list:
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _gql(query: str) -> dict:
    return _get_json(TWITCH_GQL, {"query": query},
                     {"Client-Id": TWITCH_WEB_CLIENT, "Content-Type": "application/json"})["data"]


def _moment(mid: str, url: str, start: float, end: float, views: int, title: str, signal: str) -> dict:
    return {"id": mid, "url": url, "start": max(0.0, start), "end": end, "views": views,
            "title": title, "signal": signal}


# ---------------- Twitch ----------------
def twitch_clips(login: str, limit: int = 20) -> list[dict]:
    q = ('query{user(login:"%s"){clips(first:%d,criteria:{period:LAST_WEEK,sort:VIEWS_DESC}){edges{node{'
         'slug title viewCount durationSeconds videoOffsetSeconds video{id lengthSeconds}}}}}}' % (login, limit))
    user = _gql(q).get("user") or {}
    out = []
    for e in (user.get("clips") or {}).get("edges", []):
        n = e["node"]
        if n.get("video") and n.get("videoOffsetSeconds") is not None:
            # Clip still has its VOD: fetch generous context around it.
            off = n["videoOffsetSeconds"]
            out.append(_moment(f"tw-{n['video']['id']}-{off}", f"https://www.twitch.tv/videos/{n['video']['id']}",
                               off - CONTEXT_BEFORE, off + n["durationSeconds"] + CONTEXT_AFTER,
                               n["viewCount"], n["title"], "twitch-clip"))
        else:
            # VOD expired: the clip itself (<=60 s) is all that is left.
            out.append(_moment(f"twc-{n['slug']}", f"https://clips.twitch.tv/{n['slug']}", 0, n["durationSeconds"],
                               n["viewCount"], n["title"], "twitch-clip-only"))
    return out


def twitch_vods(login: str, limit: int = 3) -> list[dict]:
    q = 'query{user(login:"%s"){videos(first:%d,type:ARCHIVE,sort:TIME){edges{node{id title lengthSeconds viewCount}}}}}' % (login, limit)
    user = _gql(q).get("user") or {}
    return [e["node"] for e in (user.get("videos") or {}).get("edges", [])]


def _chat_count(video_id: str, offset: int, span: int) -> int:
    q = 'query{video(id:"%s"){comments(contentOffsetSeconds:%d){edges{node{contentOffsetSeconds}}}}}' % (video_id, offset)
    try:
        edges = ((_gql(q).get("video") or {}).get("comments") or {}).get("edges", [])
    except OSError:
        return 0
    return sum(1 for e in edges if offset <= e["node"]["contentOffsetSeconds"] < offset + span)


def twitch_chat_peaks(login: str, count: int = 5, span: int = 30) -> list[dict]:
    """hotclip-style: chat messages per 30 s across the latest VOD; the busiest windows are the moments."""
    vods = twitch_vods(login, 1)
    if not vods:
        return []
    v = vods[0]
    offsets = list(range(60, max(61, v["lengthSeconds"] - span), span))
    with ThreadPoolExecutor(8) as pool:
        counts = list(pool.map(lambda o: _chat_count(v["id"], o, span), offsets))
    ranked = sorted(zip(counts, offsets), reverse=True)
    out, used = [], []
    for c, o in ranked:
        if c < 3 or len(out) >= count:
            break
        if any(abs(o - u) < 120 for u in used):
            continue
        used.append(o)
        out.append(_moment(f"twchat-{v['id']}-{o}", f"https://www.twitch.tv/videos/{v['id']}",
                           o - CONTEXT_BEFORE, o + span + CONTEXT_AFTER, c, v["title"], f"twitch-chat({c} msgs)"))
    return out


# ---------------- Kick ----------------
def kick_clips(channel: str, limit: int = 20) -> list[dict]:
    data = _get_json(f"https://kick.com/api/v2/channels/{channel}/clips?sort=view&time=week")
    out = []
    for c in (data.get("clips") or [])[:limit]:
        # Kick clips carry no VOD offset, so the clip (up to 60 s) is the window.
        out.append(_moment(f"kc-{c['id']}", c["video_url"], 0, c.get("duration") or 60,
                           c.get("views") or c.get("view_count") or 0, c.get("title", ""), "kick-clip"))
    return out


# ---------------- YouTube ----------------
def youtube_heat_moments(channel_videos_url: str, count: int = 5, recent: int = 4) -> list[dict]:
    """Top 'most replayed' peaks of the channel's recent uploads (metadata only, no download)."""
    listing = json.loads(subprocess.run(
        ["yt-dlp", "--no-warnings", "--flat-playlist", "--playlist-items", f"1-{recent}", "-J", channel_videos_url],
        capture_output=True, text=True, check=True).stdout)
    out = []
    for e in listing.get("entries") or []:
        url = f"https://www.youtube.com/watch?v={e['id']}"
        try:
            info = json.loads(subprocess.run(["yt-dlp", "--no-warnings", "--skip-download", "-J", url],
                                             capture_output=True, text=True, check=True).stdout)
        except subprocess.CalledProcessError:
            continue
        heat = sorted(info.get("heatmap") or [], key=lambda h: -h["value"])
        used = []
        for h in heat:
            mid = (h["start_time"] + h["end_time"]) / 2
            if mid < 30 or any(abs(mid - u) < 90 for u in used):
                continue  # intros always look replayed; keep peaks apart
            used.append(mid)
            out.append(_moment(f"yt-{e['id']}-{int(mid)}", url, mid - 45, mid + 35,
                               int((info.get("view_count") or 0) * h["value"]), info.get("title", ""),
                               f"yt-most-replayed({h['value']:.2f})"))
            if len(used) >= 2:
                break
    return sorted(out, key=lambda m: -m["views"])[:count]


# ---------------- dispatcher ----------------
def moments_for(source: str) -> list[dict]:
    """Best-first list of candidate moments for a source URL."""
    s = source.split("?")[0].rstrip("/")
    m = re.match(r"https?://(www\.)?twitch\.tv/([^/]+)", s)
    if m:
        login = m.group(2).lower()
        found = twitch_clips(login)
        return found if len(found) >= 3 else found + twitch_chat_peaks(login)
    m = re.match(r"https?://(www\.)?kick\.com/([^/]+)", s)
    if m:
        return kick_clips(m.group(2).lower())
    if "youtube.com" in s:
        if not s.endswith("/videos"):
            s += "/videos"
        return youtube_heat_moments(s)
    return []


if __name__ == "__main__":
    import sys
    for mo in moments_for(sys.argv[1])[:8]:
        print(f"{mo['views']:>7}  {mo['start']:>8.0f}-{mo['end']:<8.0f} {mo['signal']:<26} {mo['title'][:50]}  {mo['url']}")
