"""Commit data/ without losing entries when another run pushed first.

Runs can overlap (a cancelled run still commits), so `git pull --rebase` conflicts on clips.json.
Instead: keep this run's files aside, reset to the remote, and merge by key.
"""
import json
import subprocess
import sys
from pathlib import Path

DATA = Path("data")


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


def main() -> None:
    mine_clips = load(DATA / "clips.json", [])
    mine_seen = load(DATA / "seen.json", [])
    mine_campaigns = (DATA / "campaigns.json").read_text(encoding="utf-8") if (DATA / "campaigns.json").exists() else None
    git("fetch", "-q", "origin", "main")
    git("reset", "-q", "--hard", "origin/main")
    theirs_clips = load(DATA / "clips.json", [])
    by_file = {c["file"]: c for c in theirs_clips}
    by_file.update({c["file"]: c for c in mine_clips})  # this run's view of a clip wins
    merged = sorted(by_file.values(), key=lambda c: c.get("created", ""), reverse=True)
    DATA.mkdir(exist_ok=True)
    (DATA / "clips.json").write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    (DATA / "seen.json").write_text(json.dumps(sorted(set(load(DATA / "seen.json", [])) | set(mine_seen))))
    if mine_campaigns is not None:
        (DATA / "campaigns.json").write_text(mine_campaigns, encoding="utf-8")
    git("add", "data/")
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode:
        git("commit", "-qm", "bot: update clips/campaigns [skip ci]")
        git("push", "-q", "origin", "HEAD:main")
    print(f"clips: {len(merged)}")


if __name__ == "__main__":
    sys.exit(main())
