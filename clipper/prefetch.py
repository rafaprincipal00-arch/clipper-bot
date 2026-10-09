"""Cloud side of the PC prefetch (scripts/yt_prefetch.py): fetch the moment windows the PC downloaded.

The draft release "prefetch" holds prefetch.json + one mp4 per moment. `load()` downloads them into
work/prefetch, deletes them from the release (raw source never stays online) and returns
{creator: [moment, ...]} where each moment has "local" = path of its window.
"""
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "work" / "prefetch"


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Asset downloads redirect to signed storage URLs that reject our GitHub token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return urllib.request.Request(newurl, headers={"Accept": "application/octet-stream"})


def _call(url: str, method: str = "GET", accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": accept})
    with urllib.request.build_opener(_NoAuthRedirect).open(req, timeout=300) as r:
        return r.read()


def load() -> dict[str, list[dict]]:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (repo and os.environ.get("GH_TOKEN")):
        return {}
    rels = json.loads(_call(f"https://api.github.com/repos/{repo}/releases?per_page=30"))
    rel = next((r for r in rels if r.get("draft") and r.get("name") == "prefetch"), None)
    if not rel:
        return {}
    assets = {a["name"]: a for a in rel.get("assets", [])}
    if "prefetch.json" not in assets:
        return {}
    manifest = json.loads(_call(assets["prefetch.json"]["url"], accept="application/octet-stream"))
    DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[dict]] = {}
    for e in manifest:
        a = assets.get(e["asset"])
        if not a:
            continue
        path = DIR / e["asset"]
        path.write_bytes(_call(a["url"], accept="application/octet-stream"))
        out.setdefault(e["creator"], []).append({**e["moment"], "local": str(path)})
    for a in assets.values():  # consumed: nothing raw stays online
        _call(a["url"], method="DELETE")
    print(f"  prefetch: {sum(len(v) for v in out.values())} windows from the PC "
          f"({', '.join(f'{k}: {len(v)}' for k, v in out.items())})")
    return out
