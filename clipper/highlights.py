"""Turn a viral moment's transcript into a short multi-cut edit (Gemini picks the kept segments)."""
import json
import os
import time
import urllib.request


EDIT_PROMPT = """You are a top short-form editor (TikTok / YouTube Shorts / Reels) cutting a clip of {creator}.
Viewers marked this moment as viral: "{title}". Below is the word-timestamped transcript (seconds) of the
source window around it.

Build a fast, dopamine-heavy edit of {min_len}-{max_len} seconds total (NEVER under {min_len}s: viewers need the
context to get the payoff) from many kept segments:
- Second 0 is the hook: the strongest line or reaction, even if it comes later in the window. Then only the
  set-up needed to understand it, then the payoff. Keep chronological order apart from that opening hook.
- Cut hard and often: a new cut every 2-5 seconds is ideal. Drop filler ("uh", "like", "you know"), repeats,
  every pause, side-tangents and chat-reading that adds nothing. Long moments must be compressed, not truncated.
- NEVER cut mid-word or mid-sentence and never remove context the payoff depends on. Keep enough set-up
  (what is happening, who says what to whom) that a stranger scrolling past understands the moment.
- Segments must use the transcript's timestamps, each at least 1.0 s long.
Score viral potential 0-100 and be harsh. It needs a real payoff: a reaction, a fail, a roast, drama, a
shocking line, a funny exchange with a punchline. Someone just commenting, reading chat, explaining or
chatting without a payoff scores under 40 even if it is mildly amusing.
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


# Below this a clip has no context; the user wants 20-30 s minimum (CLIP_MIN_S overrides).
MIN_TOTAL = float(os.environ.get("CLIP_MIN_S", "20"))
MAX_TOTAL = float(os.environ.get("CLIP_MAX_S", "40"))


def ensure_min(segs: list[tuple[float, float]], lo: float, hi: float, min_total: float = MIN_TOTAL,
               max_len: float = 40) -> list[tuple[float, float]]:
    """Too little kept? Use one continuous stretch around the chosen action instead (the visuals carry it)."""
    if sum(e - s for s, e in segs) >= min_total or hi - lo <= 0:
        return segs
    mid = (segs[0][0] + segs[-1][1]) / 2 if segs else (lo + hi) / 2
    span = min(max(min_total + 5, 20.0), max_len, hi - lo)
    s = min(max(lo, mid - span / 2), hi - span)
    return [(s, s + span)]



def micro_cut(segs: list[tuple[float, float]], words: list[dict], gap: float = 0.25,
              beat: float = 3.0) -> list[tuple[float, float]]:
    """Fast-cut pass: drop every pause > `gap` inside the kept segments (jump cuts) and split anything
    longer than `beat` s at a word boundary, so the renderer changes zoom at least every ~3 s."""
    out = []
    for s, e in segs:
        inside = [w for w in words if w["start"] >= s - 0.05 and w["end"] <= e + 0.05]
        parts, cur = [], None
        for w in inside:
            ws, we = max(s, w["start"] - 0.06), min(e, w["end"] + 0.08)
            if cur and ws - cur[1] <= gap:
                cur[1] = we
            else:
                if cur:
                    parts.append(cur)
                cur = [ws, we]
        if cur:
            parts.append(cur)
        if not parts:  # no speech in it (gameplay): keep it whole, the beat split below still adds cuts
            parts = [[s, e]]
        for ps, pe in parts:
            while pe - ps > beat + 1.0:
                cut = ps + beat
                ends = [w["end"] + 0.08 for w in inside if ps + 1.5 < w["end"] + 0.08 <= ps + beat + 0.8]
                if ends:
                    cut = min(ends, key=lambda x: abs(x - (ps + beat)))
                out.append((ps, cut))
                ps = cut
            if pe - ps >= 0.4:
                out.append((ps, pe))
    return out or segs


def _phrases(words: list[dict], lo: float, hi: float, pause: float = 0.35) -> list[tuple[float, float]]:
    """Speech stretches inside [lo, hi], split on pauses."""
    out: list[list[float]] = []
    for w in words:
        if w["start"] < lo or w["end"] > hi:
            continue
        if out and w["start"] - out[-1][1] <= pause:
            out[-1][1] = w["end"]
        else:
            out.append([w["start"], w["end"]])
    return [(max(lo, s - 0.06), min(hi, e + 0.08)) for s, e in out]


def total(segs: list[tuple[float, float]]) -> float:
    return sum(e - s for s, e in segs)


def pad_to_min(segs: list[tuple[float, float]], words: list[dict], lo: float, hi: float,
               min_total: float = MIN_TOTAL, max_len: float = MAX_TOTAL) -> list[tuple[float, float]]:
    """Grow a too-short edit with the surrounding speech (context), nearest first, keeping the opening
    hook in place; if the window runs out of speech, extend the last shot with what follows (visuals)."""
    if not segs or total(segs) >= min_total:
        return segs
    hook, body = (segs[:1], segs[1:]) if len(segs) > 1 and segs[0][0] > segs[1][0] else ([], list(segs))
    kept = hook + body

    def overlaps(p: tuple[float, float]) -> bool:
        return any(p[0] < e and p[1] > s for s, e in kept)

    span_s, span_e = (min(s for s, _ in body), max(e for _, e in body)) if body else segs[0]
    extra = sorted((p for p in _phrases(words, lo, hi) if not overlaps(p)),
                   key=lambda p: max(span_s - p[1], p[0] - span_e, 0))
    for p in extra:
        if total(hook + body) >= min_total:
            break
        room = max_len - total(hook + body)
        if room < 1.0:
            break
        p = (p[0], min(p[1], p[0] + room))
        body = sorted(body + [p])
    if total(hook + body) < min_total and body:
        # Not enough speech around it (gameplay): let the last shot run on.
        s, e = body[-1]
        body[-1] = (s, min(hi, e + (min_total - total(hook + body))))
    if total(hook + body) < min_total and body:
        s, e = body[0]
        body[0] = (max(lo, s - (min_total - total(hook + body))), e)
    return hook + body


def pick_edit(words: list[dict], creator: str, title: str, lo: float, hi: float,
              min_len: int = int(MIN_TOTAL), max_len: int = int(MAX_TOTAL)) -> dict | None:
    if not words:
        return None
    res = _gemini_json(EDIT_PROMPT.format(creator=creator, title=title, min_len=min_len, max_len=max_len,
                                          transcript=_transcript_lines(words)))
    if not res:
        return None
    segs = clean_segments(res.get("segments"), words, lo, hi, max_len)
    if not segs:
        return {**res, "segments": ensure_min(segs, lo, hi, max_len=max_len)}
    return {**res, "segments": pad_to_min(segs, words, lo, hi, max_len=max_len)}


def fallback_edit(words: list[dict], lo: float, hi: float, max_len: int = int(MAX_TOTAL)) -> dict:
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

