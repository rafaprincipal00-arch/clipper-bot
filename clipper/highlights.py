"""Find clip-worthy moments: loudness peaks first, then an LLM picks the cut."""
import json
import os
import re
import subprocess
import time
import urllib.request


def loudness_per_second(audio: str) -> list[float]:
    """Mean volume (dB) per second via ffmpeg astats; cheap even on 6 h VODs."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", audio, "-vn", "-ac", "1", "-ar", "8000",
        "-af", "asetnsamples=8000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    levels = []
    for m in re.finditer(r"RMS_level=(-?[\d.]+|-inf)", proc.stderr):
        v = m.group(1)
        levels.append(-90.0 if v == "-inf" else float(v))
    return levels


def peak_windows(levels: list[float], count: int, window: int = 90, skip_start: int = 120) -> list[tuple[int, int]]:
    """Top `count` non-overlapping windows by the loudest 10 s burst inside each."""
    n = len(levels)
    if n <= window:
        return [(0, n)]
    burst = []
    for i in range(n - 10):
        burst.append(sum(levels[i:i + 10]) / 10)
    order = sorted(range(skip_start if n > skip_start * 3 else 0, len(burst)), key=lambda i: -burst[i])
    chosen: list[tuple[int, int]] = []
    for i in order:
        start = max(0, i - window // 2)
        end = min(n, start + window)
        if all(end <= s or start >= e for s, e in chosen):
            chosen.append((start, end))
        if len(chosen) == count:
            break
    return sorted(chosen)


PROMPT = """You are an expert short-form clipper for TikTok, YouTube Shorts and Instagram Reels.
Below is a timestamped transcript window (seconds) from a livestream/video by {creator}.
Pick the single best self-contained moment of {min_len}-{max_len} seconds: a strong hook in the
first 2 seconds, a payoff, no dead air. Start 1-2 s before the action, end right after the payoff.
Score its viral potential 0-100 (be harsh: boring = under 40).
Reply ONLY with JSON: {{"start": float, "end": float, "score": int, "hook": "max 6 words, caps ok",
"title": "post caption under 90 chars, no hashtags"}}

Transcript:
{transcript}"""


def pick_with_llm(words: list[dict], creator: str, min_len: int = 20, max_len: int = 55) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not words:
        return None
    lines, cur, cur_start = [], [], None
    for w in words:
        cur_start = w["start"] if cur_start is None else cur_start
        cur.append(w["word"])
        if len(cur) >= 12:
            lines.append(f"[{cur_start:.1f}] {' '.join(cur)}")
            cur, cur_start = [], None
    if cur:
        lines.append(f"[{cur_start:.1f}] {' '.join(cur)}")
    models = [os.environ.get("GEMINI_MODEL", "gemini-flash-latest"), "gemini-flash-lite-latest", "gemini-2.5-flash"]
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(creator=creator, min_len=min_len, max_len=max_len, transcript="\n".join(lines))}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    for attempt, model in enumerate(models * 2):
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.load(r)
            pick = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
            if isinstance(pick, list):
                pick = pick[0]
            return pick if pick["end"] - pick["start"] >= 8 else None
        except (OSError, KeyError, ValueError, IndexError) as e:
            print(f"  LLM pick failed ({model}): {e}")
            time.sleep(3 * (attempt + 1))
    return None


def fallback_pick(words: list[dict], win_start: float, win_end: float) -> dict:
    """No LLM: centre a 40 s cut on the window and use its first words as hook."""
    mid = (win_start + win_end) / 2
    start, end = max(win_start, mid - 22), min(win_end, mid + 18)
    inside = [w["word"] for w in words if start <= w["start"] <= end]
    hook = " ".join(inside[:5]).upper() if inside else "WAIT FOR IT"
    return {"start": start, "end": end, "score": 50, "hook": hook, "title": " ".join(inside[:14])}
