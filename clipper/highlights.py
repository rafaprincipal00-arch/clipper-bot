"""Turn a viral moment's transcript into a short multi-cut edit (Gemini picks the kept segments)."""
import json
import os
import time
import urllib.request


EDIT_PROMPT = """You are a top short-form editor (TikTok / YouTube Shorts / Reels) cutting a clip of {creator}.
Viewers marked this moment as viral: "{title}". Below is the word-timestamped transcript (seconds) of the
source window around it.

Build a fast, dopamine-heavy edit of AT MOST {max_len} seconds total (shorter is fine if the moment is complete;
aim for {min_len}-{max_len}s) from many kept segments:
- Second 0 is the hook: the strongest line or reaction, even if it comes later in the window. Then only the
  set-up needed to understand it, then the payoff. Keep chronological order apart from that opening hook.
- Cut hard and often: a new cut every 2-5 seconds is ideal. Drop filler ("uh", "like", "you know"), repeats,
  every pause, side-tangents and chat-reading that adds nothing. Long moments must be compressed, not truncated.
- NEVER cut mid-word or mid-sentence and never remove context the payoff depends on.
- Segments must use the transcript's timestamps, each at least 1.0 s long.
Score viral potential 0-100 (be harsh: boring = under 40).
Pick the music mood of the moment: one of funny, awkward, sus, chaos, drama, hype, chill.
Hook and title must be brand-safe: no slurs or profanity (campaigns auto-reject them).
Reply ONLY with JSON: {{"segments": [[start, end], ...], "score": int, "mood": "funny",
"hook": "max 6 words, caps ok", "title": "post caption under 90 chars, no hashtags"}}

Transcript:
{transcript}"""


def _gemini_json(prompt: str) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    models = [os.environ.get("GEMINI_MODEL", "gemini-flash-latest"), "gemini-flash-lite-latest", "gemini-2.5-flash"]
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    for attempt, model in enumerate(models * 2):
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.load(r)
            out = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
            return out[0] if isinstance(out, list) else out
        except (OSError, KeyError, ValueError, IndexError) as e:
            print(f"  LLM failed ({model}): {e}")
            time.sleep(3 * (attempt + 1))
    return None


def _transcript_lines(words: list[dict]) -> str:
    """One line per phrase, split on pauses > 0.6 s, so segment edges fall between phrases."""
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 9
        if gap > 0.6 or len(cur) >= 14:
            lines.append(f"[{cur[0]['start']:.2f}-{cur[-1]['end']:.2f}] {' '.join(x['word'] for x in cur)}")
            cur = []
    return "\n".join(lines)


def _snap(t: float, words: list[dict], edge: str) -> float:
    """Move a cut point off any word it would slice (to the word's start or end)."""
    for w in words:
        if w["start"] < t < w["end"]:
            return w["start"] if edge == "start" else w["end"]
    return t


def clean_segments(raw: list, words: list[dict], lo: float, hi: float, max_len: float) -> list[tuple[float, float]]:
    segs = []
    for pair in raw or []:
        try:
            s, e = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        s = max(lo, _snap(s, words, "start") - 0.08)
        e = min(hi, _snap(e, words, "end") + 0.12)
        if e - s >= 1.0:
            segs.append((s, e))
    # Merge overlaps / near-touching segments (a 0.15 s gap is not a real cut).
    merged: list[tuple[float, float]] = []
    for s, e in segs:
        if merged and s - merged[-1][1] < 0.15 and s >= merged[-1][0]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    total, out = 0.0, []
    for s, e in merged:  # enforce the hard length cap
        if total + (e - s) > max_len:
            e = s + (max_len - total)
            if e - s >= 1.0:
                out.append((s, _snap(e, words, "start")))
            break
        out.append((s, e))
        total += e - s
    return out


MIN_TOTAL = 15.0  # below this a clip has no context (happens on gameplay with little speech)


def ensure_min(segs: list[tuple[float, float]], lo: float, hi: float, min_total: float = MIN_TOTAL,
               max_len: float = 40) -> list[tuple[float, float]]:
    """Too little kept? Use one continuous stretch around the chosen action instead (the visuals carry it)."""
    if sum(e - s for s, e in segs) >= min_total or hi - lo <= 0:
        return segs
    mid = (segs[0][0] + segs[-1][1]) / 2 if segs else (lo + hi) / 2
    span = min(max(min_total + 5, 20.0), max_len, hi - lo)
    s = min(max(lo, mid - span / 2), hi - span)
    return [(s, s + span)]


def pick_edit(words: list[dict], creator: str, title: str, lo: float, hi: float,
              min_len: int = 20, max_len: int = 40) -> dict | None:
    if not words:
        return None
    res = _gemini_json(EDIT_PROMPT.format(creator=creator, title=title, min_len=min_len, max_len=max_len,
                                          transcript=_transcript_lines(words)))
    if not res:
        return None
    segs = clean_segments(res.get("segments"), words, lo, hi, max_len)
    return {**res, "segments": ensure_min(segs, lo, hi, max_len=max_len)}


def fallback_edit(words: list[dict], lo: float, hi: float, max_len: int = 40) -> dict:
    """No LLM: keep speech, cut every pause > 0.35 s (jump cuts), capped at max_len."""
    raw, cur = [], None
    for w in words:
        if cur and w["start"] - cur[1] <= 0.35:
            cur[1] = w["end"]
        else:
            if cur:
                raw.append(cur)
            cur = [w["start"], w["end"]]
    if cur:
        raw.append(cur)
    segs = ensure_min(clean_segments(raw, words, lo, hi, max_len), lo, hi, max_len=max_len)
    inside = [w["word"] for w in words if segs[0][0] <= w["start"]]
    return {"segments": segs, "score": 50, "hook": " ".join(inside[:5]).upper() or "WAIT FOR IT",
            "title": " ".join(inside[:14]), "mood": "funny", "fallback": True}

