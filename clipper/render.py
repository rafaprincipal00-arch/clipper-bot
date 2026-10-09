"""Cut, reframe to 9:16 and burn top-clipper style captions, sharpening and ducked music with ffmpeg."""
import random
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
MUSIC = ROOT / "assets" / "music"
SFX = ROOT / "assets" / "sfx"
FONT_FILE = FONTS / "Montserrat-Black.ttf"
MUSIC_CREDIT = "Music: Kevin MacLeod (incompetech.com) CC BY 4.0"

# ASS colours are &HAABBGGRR.
WHITE, BLACK = "&H00FFFFFF", "&H00000000"
HIGHLIGHTS = ["&H0000E5FF", "&H0055FF3C", "&H002E7AFF"]  # yellow, green, orange
EMPHASIS = "&H003030FF"  # red: the words that carry the joke or the stakes

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


def _key(word: str) -> str:
    return "".join(ch for ch in word.lower() if ch.isalnum())


def write_ass(words: list[dict], start: float, end: float, hook: str, path: Path, per_line: int = 3,
              emphasis: list[str] | None = None) -> None:
    """2-3 big words on screen; the spoken word pops (scale) in a highlight colour that rotates per line.
    Emphasis words (picked by the LLM) pop bigger and red."""
    strong = {_key(w) for e in (emphasis or []) for w in e.split()}
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
                if k == j and _key(other["word"]) in strong:
                    parts.append(f"{{\\c{EMPHASIS}\\fscx135\\fscy135\\t(0,120,\\fscx118\\fscy118)}}{txt}{{\\r}}")
                elif k == j:
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


# Only beds the user confirmed he hears in Reels/TikToks; the rest were dropped as "never goes viral".
APPROVED = ["Run_Amok"]
MOODS = dict.fromkeys(("funny", "awkward", "sus", "chaos", "drama", "hype", "chill"), APPROVED)


def pick_music(seed: str, mood: str = "funny") -> Path | None:
    """A recognisable meme bed matching the clip's mood (picked by the LLM), falling back to any track."""
    names = MOODS.get(mood) or MOODS["funny"]
    tracks = [MUSIC / f"{n}.m4a" for n in names if (MUSIC / f"{n}.m4a").exists()] or sorted(MUSIC.glob("*.m4a"))
    return random.Random(seed).choice(tracks) if tracks else None


def remap_words(words: list[dict], segments: list[tuple[float, float]]) -> list[dict]:
    """Source-time words -> edited-timeline words (words in cut-out parts are dropped)."""
    out, acc = [], 0.0
    for s, e in segments:
        for w in words:
            if s <= w["start"] < e:
                out.append({**w, "start": w["start"] - s + acc, "end": min(w["end"], e) - s + acc})
        acc += e - s
    return out


ZOOMS = (1.0, 1.18, 1.06, 1.28)  # a different punch-in on each cut hides the jump and keeps it moving

# Self-made SFX (scripts/make_sfx.py, no licence needed), kept low under the voice.
SFX_GAIN = {"pop": 0.35, "whoosh": 0.22, "boom": 0.45}


def sfx_plan(segments: list[tuple[float, float]]) -> list[tuple[str, float]]:
    """Pop when the hook lands, a whoosh on every cut, a bass hit when the last (payoff) shot starts."""
    if not SFX.exists():
        return []
    hits, t = [("pop", 0.0)], 0.0
    starts = []
    for s, e in segments:
        starts.append(t)
        t += e - s
    for k, st in enumerate(starts[1:], 1):
        hits.append(("boom" if k == len(starts) - 1 and len(starts) > 2 else "whoosh", max(0.0, st - 0.08)))
    return [(n, x) for n, x in hits if (SFX / f"{n}.wav").exists()]


def render_edit(src: str, segments: list[tuple[float, float]], info: dict, ass: Path, out: Path,
                credit: str = "", mood: str = "funny", style: str = "vertical", with_music: bool = True) -> None:
    """Cut `segments` out of `src`, frame each for 9:16 (layout `info`), alternate punch-in zoom on the
    cuts, then burn captions, add a fade-in and the ducked music bed. One ffmpeg pass."""
    from . import layout

    n = len(segments)
    g = [f"[0:v]split={n}" + "".join(f"[r{i}]" for i in range(n)) if n > 1 else "[0:v]null[r0]",
         f"[0:a]asplit={n}" + "".join(f"[q{i}]" for i in range(n)) if n > 1 else "[0:a]anull[q0]"]
    for i, (s, e) in enumerate(segments):
        g.append(f"[r{i}]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS[t{i}]")
        g.append(layout.filtergraph(info, f"[t{i}]", f"[l{i}]", t_off=s, t_end=e, sfx=str(i), style=style))
        z = ZOOMS[i % len(ZOOMS)]
        if i == 0:
            # Opening punch: starts 25 % in and eases out over 0.5 s, so frame 1 already moves.
            g.append(f"[l{i}]scale=w='trunc(1080*(1+0.25*pow(max(0,1-t/0.5),2))/2)*2':h=-2:eval=frame:flags=lanczos,"
                     f"crop=1080:1920,setsar=1[z{i}]")
        elif z > 1:
            g.append(f"[l{i}]scale={int(1080 * z) // 2 * 2}:{int(1920 * z) // 2 * 2}:flags=lanczos,"
                     f"crop=1080:1920,setsar=1[z{i}]")
        else:
            g.append(f"[l{i}]setsar=1[z{i}]")
        g.append(f"[q{i}]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.02[p{i}]")
    g.append("".join(f"[z{i}][p{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    credit_f = ""
    if credit:
        safe = credit.replace(":", "\\:").replace("'", "")
        credit_f = (f",drawtext=fontfile='{_rel(FONT_FILE)}':text='{safe}':fontcolor=white@0.9:fontsize=38"
                    ":x=(w-tw)/2:y=h-190:box=1:boxcolor=black@0.4:boxborderw=14")
    g.append(f"[vc]subtitles='{_rel(ass)}':fontsdir='{_rel(FONTS)}'{credit_f},fade=in:st=0:d=0.12:color=white[v]")
    # TikTok copy is rendered without a bed: the poster adds a trending song from TikTok's licensed library.
    music = pick_music(out.stem, mood) if with_music else None
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    voice = "[ac]"
    hits = sfx_plan(segments)
    if hits:
        first = 2 if music else 1
        names = sorted({name for name, _ in hits})
        for name in names:
            cmd += ["-i", _rel(SFX / f"{name}.wav")]
        for k, name in enumerate(names):
            uses = [t for nm, t in hits if nm == name]
            g.append(f"[{first + k}:a]aresample=48000,volume={SFX_GAIN[name]},asplit={len(uses)}"
                     + "".join(f"[{name}{m}]" for m in range(len(uses))))
            for m, t in enumerate(uses):
                ms = int(t * 1000)
                g.append(f"[{name}{m}]adelay={ms}|{ms}[{name}d{m}]")
        tags = "".join(f"[{name}d{m}]" for name in names for m in range(sum(1 for nm, _ in hits if nm == name)))
        g.append("[ac]aresample=48000[ac48]")
        g.append(f"[ac48]{tags}amix=inputs={len(hits) + 1}:duration=first:normalize=0[vfx]")
        voice = "[vfx]"
    if music:
        cmd[cmd.index(src) + 1:cmd.index(src) + 1] = ["-stream_loop", "-1", "-i", _rel(music)]
        g.append(f"{voice}aresample=48000,asplit=2[voice][key]")
        g.append("[1:a]aresample=48000,volume=0.22[bgm]")
        g.append("[bgm][key]sidechaincompress=threshold=0.04:ratio=10:attack=15:release=350[duck]")
        g.append("[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    else:
        g.append(f"{voice}loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    cmd += ["-filter_complex", ";".join(g), "-map", "[v]", "-map", "[aout]", "-shortest",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out.resolve())]
    subprocess.run(cmd, check=True, cwd=ROOT)

