"""Cut, reframe to 9:16 and burn top-clipper style captions, sharpening and ducked music with ffmpeg."""
import random
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
MUSIC = ROOT / "assets" / "music"
FONT_FILE = FONTS / "Montserrat-Black.ttf"
MUSIC_CREDIT = "Music: Kevin MacLeod (incompetech.com) CC BY 4.0"

# ASS colours are &HAABBGGRR.
WHITE, BLACK = "&H00FFFFFF", "&H00000000"
HIGHLIGHTS = ["&H0000E5FF", "&H0055FF3C", "&H002E7AFF"]  # yellow, green, orange

ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Montserrat Black,96,{WHITE},{WHITE},{BLACK},&H80000000,1,0,0,0,100,100,0,0,1,9,4,2,50,50,520,1
Style: Hook,Montserrat Black,74,{BLACK},{BLACK},&H0000E5FF,&H0000E5FF,1,0,0,0,100,100,0,0,3,18,0,8,70,70,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _clean(word: str) -> str:
    return word.strip().upper().replace("{", "").replace("}", "")


def write_ass(words: list[dict], start: float, end: float, hook: str, path: Path, per_line: int = 3) -> None:
    """2-3 big words on screen; the spoken word pops (scale) in a highlight colour that rotates per line."""
    rel = [w for w in words if start <= w["start"] < end]
    events = [f"Dialogue: 2,{_ts(0)},{_ts(min(3.0, end - start))},Hook,,0,0,0,,"
              f"{{\\fad(0,250)}}{_clean(hook)}"]
    for i in range(0, len(rel), per_line):
        group = rel[i:i + per_line]
        colour = HIGHLIGHTS[(i // per_line) % len(HIGHLIGHTS)]
        line_end = (rel[i + per_line]["start"] if i + per_line < len(rel) else group[-1]["end"] + 0.3) - start
        for j, w in enumerate(group):
            w_start = w["start"] - start
            w_end = (group[j + 1]["start"] - start) if j + 1 < len(group) else line_end
            parts = []
            for k, other in enumerate(group):
                txt = _clean(other["word"])
                if k == j:
                    parts.append(f"{{\\c{colour}\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}}{txt}{{\\r}}")
                else:
                    parts.append(txt)
            events.append(f"Dialogue: 0,{_ts(w_start)},{_ts(max(w_end, w_start + 0.05))},Cap,,0,0,0,,{' '.join(parts)}")
    path.write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8")


def _rel(p: Path) -> str:
    """ffmpeg filter args break on Windows drive colons; run from ROOT and pass relative paths."""
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix().replace(":", "\\:")


def pick_music(seed: str) -> Path | None:
    tracks = sorted(MUSIC.glob("*.m4a"))
    return random.Random(seed).choice(tracks) if tracks else None


def render_vertical(src: str, start: float, end: float, ass: Path, out: Path, credit: str = "") -> None:
    """Blurred background + sharpened, graded 16:9 source + captions + music ducked under the voice."""
    credit_f = ""
    if credit:
        safe = credit.replace(":", "\\:").replace("'", "")
        credit_f = (f",drawtext=fontfile='{_rel(FONT_FILE)}':text='{safe}':fontcolor=white@0.9:fontsize=38"
                    ":x=(w-tw)/2:y=h-190:box=1:boxcolor=black@0.4:boxborderw=14")
    vf = (
        "[0:v]split=2[a][b];"
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:2,eq=brightness=-0.12:saturation=1.3[bg];"
        # Slight centre crop = tighter framing; lanczos + unsharp + grade = crisp, punchy look.
        "[b]crop=iw*0.86:ih*0.86,scale=1080:-2:flags=lanczos,unsharp=5:5:0.9:3:3:0.3,"
        "eq=contrast=1.07:saturation=1.22:gamma=0.98[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2-60,"
        f"subtitles='{_rel(ass)}':fontsdir='{_rel(FONTS)}'{credit_f},"
        "fade=in:st=0:d=0.12:color=white[v]"
    )
    music = pick_music(out.stem)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", src]
    if music:
        cmd += ["-stream_loop", "-1", "-i", _rel(music)]
        af = (";[0:a]aresample=48000,asplit=2[voice][key];"
              "[1:a]aresample=48000,volume=0.22[bgm];"
              "[bgm][key]sidechaincompress=threshold=0.04:ratio=10:attack=15:release=350[duck];"
              "[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
        maps = ["-map", "[v]", "-map", "[aout]"]
    else:
        af = ";[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        maps = ["-map", "[v]", "-map", "[aout]"]
    cmd += ["-filter_complex", vf + af, *maps, "-shortest",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out.resolve())]
    subprocess.run(cmd, check=True, cwd=ROOT)
