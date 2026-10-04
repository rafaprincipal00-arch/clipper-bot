"""Cut, reframe to 9:16 and burn word-level captions + hook with ffmpeg."""
import subprocess
from pathlib import Path

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial Black,78,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,2,2,60,60,560,1
Style: Hook,Arial Black,70,&H0000F0FF,&H0000F0FF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,3,4,0,8,60,60,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_ass(words: list[dict], start: float, end: float, hook: str, path: Path, per_line: int = 3) -> None:
    rel = [w for w in words if start <= w["start"] < end]
    events = [f"Dialogue: 1,{_ts(0)},{_ts(min(3.0, end - start))},Hook,,0,0,0,,{hook.upper()}"]
    for i in range(0, len(rel), per_line):
        group = rel[i:i + per_line]
        g_start = group[0]["start"] - start
        g_end = (rel[i + per_line]["start"] if i + per_line < len(rel) else group[-1]["end"]) - start
        # Highlight the active word karaoke-style.
        parts = []
        for w in group:
            dur_cs = max(1, int((w["end"] - w["start"]) * 100))
            parts.append(f"{{\\kf{dur_cs}}}{w['word'].strip().upper()}")
        events.append(f"Dialogue: 0,{_ts(g_start)},{_ts(g_end)},Cap,,0,0,0,,{' '.join(parts)}")
    path.write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8")


def render_vertical(src: str, start: float, end: float, ass: Path, out: Path, credit: str = "") -> None:
    """Blurred full-frame background + sharp 16:9 source in the middle + captions."""
    sub = str(ass).replace("\\", "/").replace(":", "\\:")
    credit_f = ""
    if credit:
        safe = credit.replace(":", "\\:").replace("'", "")
        credit_f = f",drawtext=text='{safe}':fontcolor=white@0.85:fontsize=40:x=(w-tw)/2:y=h-170:box=1:boxcolor=black@0.35:boxborderw=12"
    vf = (
        "[0:v]split=2[a][b];"
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2,eq=brightness=-0.08[bg];"
        "[b]scale=1080:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2-80,subtitles='{sub}'{credit_f}[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", src,
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
    ]
    subprocess.run(cmd, check=True)
