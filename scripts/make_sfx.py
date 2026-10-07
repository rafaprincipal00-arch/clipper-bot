"""Generate the bot's sound effects with ffmpeg (synthesised, so no licence or credit needed).

    python scripts/make_sfx.py   ->  assets/sfx/{pop,whoosh,boom}.wav
"""
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "sfx"
SOUNDS = {
    # short rising pluck for the hook text
    "pop": "aevalsrc='0.9*sin(2*PI*(500*t+6000*t*t))*exp(-35*t)':d=0.14:s=48000",
    # filtered pink-noise swish for cuts
    "whoosh": "anoisesrc=d=0.38:c=pink:a=0.9:r=48000,highpass=f=350,lowpass=f=6000,"
              "afade=t=in:d=0.16:curve=exp,afade=t=out:st=0.16:d=0.22:curve=exp",
    # falling sub-bass hit for the payoff
    "boom": "aevalsrc='0.95*sin(2*PI*(110*t-70*t*t))*exp(-5*t)':d=0.7:s=48000,lowpass=f=300",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, src in SOUNDS.items():
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src,
                        "-ac", "2", "-ar", "48000", str(OUT / f"{name}.wav")], check=True)
        print("wrote", OUT / f"{name}.wav")


if __name__ == "__main__":
    main()
