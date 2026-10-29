"""Portfolio for the paid clipping programs in config/clip_programs.json: real views per account and per program.

    python scripts/portfolio.py            # writes data/portfolio.json + data/portfolio.md (application kit)

Views come live from yt-dlp (YouTube Shorts in data/clips.json, TikTok links in data/tiktok_poster.log); followers
from the public profile pages. Run on the PC at idle priority by scripts/autopilot.py (weekly cron), ~2 min.
"""
import concurrent.futures as cf
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TT = {"pepe854146": 1, "streammoments.daily": 2, "rafael.benitez656": 3}
YT = {1: "pepestreamclips", 2: "smdailyclips", 3: "beststreamclipshq"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36", "Accept-Language": "en-US"}


def posts() -> list[dict]:
    clips = json.loads((DATA / "clips.json").read_text(encoding="utf-8"))
    by_file = {e["file"].rsplit(".", 1)[0]: e for e in clips if e.get("file")}
    out = {}
    for e in clips:
        yt = (e.get("posts") or {}).get("youtube")
        if isinstance(yt, str) and yt.startswith("https"):
            out[yt] = {"url": yt, "platform": "youtube", "account": e.get("account"), "creator": e.get("creator", ""),
                       "title": e.get("title") or e.get("hook", ""), "date": e.get("created", "")[:10]}
    log = DATA / "tiktok_poster.log"
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines() if log.exists() else []:
        m = re.search(r"^(\S+) \S+ posted (\S+)\.mp4 -> (https://www\.tiktok\.com/@([\w.]+)/\S+)", line)
        if m:
            e = by_file.get(m.group(2), {})
            out[m.group(3)] = {"url": m.group(3), "platform": "tiktok", "account": TT.get(m.group(4)),
                               "creator": e.get("creator", m.group(2)), "title": e.get("title") or e.get("hook", ""),
                               "date": m.group(1)}
    return list(out.values())


def views(p: dict) -> dict:
    try:
        r = subprocess.run([sys.executable, "-m", "yt_dlp", "--no-warnings", "--skip-download", "--print",
                            "%(view_count)s", p["url"]], capture_output=True, text=True, timeout=90)
        p["views"] = int(r.stdout.strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        p["views"] = None
    return p


def _get(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def followers() -> dict:
    out = {}
    for handle, acct in TT.items():
        try:
            m = re.search(r'"followerCount":(\d+)', _get(f"https://www.tiktok.com/@{handle}"))
            out[f"tiktok_{acct}"] = int(m.group(1)) if m else None
        except OSError:
            out[f"tiktok_{acct}"] = None
    for acct, h in YT.items():
        try:
            m = re.search(r"([\d.,]+[KM]?) subscribers", _get(f"https://www.youtube.com/@{h}/about"))
            out[f"youtube_{acct}"] = m.group(1) if m else None
        except OSError:
            out[f"youtube_{acct}"] = None
    return out


def main() -> None:
    items = posts()
    with cf.ThreadPoolExecutor(6) as ex:
        read = list(ex.map(views, items))
    items = [p for p in read if p["views"] is not None]
    for plat in ("youtube", "tiktok"):
        lost = sum(1 for p in read if p["platform"] == plat and p["views"] is None)
        if lost:  # e.g. YouTube's bot check on the server's datacenter IP: numbers below are incomplete
            print(f"WARNING: {lost}/{sum(1 for p in read if p['platform'] == plat)} {plat} links unreadable "
                  f"(views missing from the totals)")
    programs = json.loads((ROOT / "config" / "clip_programs.json").read_text(encoding="utf-8"))["programs"]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    accounts = {}
    for a in (1, 2, 3):
        mine = [p for p in items if p["account"] == a]
        accounts[a] = {"posts": len(mine), "views": sum(p["views"] for p in mine),
                       "views_last7d_posts": sum(p["views"] for p in mine if p["date"] >= week_ago),
                       "best": max((p["views"] for p in mine), default=0)}
    prog_out = []
    for pr in programs:
        mine = sorted([p for p in items if p["creator"] in pr.get("track", [])], key=lambda p: -p["views"])
        total = sum(p["views"] for p in mine)
        recent = sum(p["views"] for p in mine if p["date"] >= week_ago)
        need = pr.get("min_views") or 0
        eta = None
        if need and total < need and recent:
            eta = (datetime.now() + timedelta(days=7 * (need - total) / recent)).date().isoformat()
        prog_out.append({"id": pr["id"], "name": pr["name"], "rank": pr["rank"], "min_views": need, "clips": len(mine),
                         "views": total, "views_from_last7d_posts": recent, "progress": round(total / need, 3) if need else None,
                         "eta": eta if need and total < need else ("ya" if need and total >= need else None),
                         "top": mine[:5]})
    out = {"at": datetime.now().isoformat(timespec="minutes"), "followers": followers(), "accounts": accounts,
           "programs": prog_out}
    (DATA / "portfolio.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    (DATA / "portfolio.md").write_text(kit(out, programs), encoding="utf-8")
    for p in prog_out:
        print(f"{p['rank']}. {p['name']}: {p['clips']} clips, {p['views']} vistas / {p['min_views']} (ETA {p['eta']})")


def kit(out: dict, programs: list[dict]) -> str:
    """Application kit: per program, the pitch (EN/ES) filled with our real numbers and best links."""
    f, acc = out["followers"], out["accounts"]
    lines = [f"# Kit de solicitud - datos reales del {out['at']}", "",
             "Cuentas: 1 TikTok @pepe854146 / YT @pepestreamclips; 2 TikTok @streammoments.daily / YT @smdailyclips; "
             "3 TikTok @rafael.benitez656 / YT @beststreamclipshq", ""]
    for a in (1, 2, 3):
        lines.append(f"- Cuenta {a}: {acc[a]['posts']} posts, {acc[a]['views']} vistas totales, mejor clip {acc[a]['best']}, "
                     f"TikTok {f.get(f'tiktok_{a}')} seguidores, YouTube {f.get(f'youtube_{a}')} suscriptores")
    meta = {p["id"]: p for p in programs}
    for p in out["programs"]:
        m = meta[p["id"]]
        a = m.get("account")
        links = "\n".join(f"  - {t['views']} vistas - {t['creator']} - {t['url']}" for t in p["top"]) or "  - (aun sin clips)"
        es = m.get("lang") == "es"
        who = m.get("who") or m["creators"].split(" (")[0]
        stats = (f"{p['clips']} clips de {who}, {p['views']} vistas reales" if es else
                 f"So far {p['clips']} clips of them, {p['views']} real views") if p["clips"] else ""
        pitch_en = (f"Hi! We run {('@' + list(TT)[a - 1]) if a else 'our'} TikTok + YouTube Shorts pages and clip {who} every day: "
                    f"vertical 1080x1920, hook in the first second, burned-in captions, 20-40 s, no reposts, no bots. "
                    f"{stats + '. ' if stats else ''}Best clips below. We'd love to join the program and follow your rules "
                    f"(tags, credit, watermark) to the letter.")
        pitch_es = (f"¡Hola! Llevamos las cuentas {('@' + list(TT)[a - 1]) if a else ''} de TikTok y YouTube Shorts y clipeamos a "
                    f"{who} a diario: vertical 1080x1920, gancho en el primer segundo, subtítulos, 20-40 s, sin reposts ni bots. "
                    f"{stats + '. ' if stats else ''}Abajo los mejores clips. Nos encantaría entrar al programa y seguir sus "
                    f"reglas (tags, crédito, marca de agua) al pie de la letra.")
        lines += ["", f"## {p['rank']}. {p['name']}", f"- Dónde: {m['where']['how']} -> {m['where']['url']}",
                  f"- Pago: {m['pay']}", f"- Requisitos: {m['requirements']}", f"- Reglas: {m['rules']}",
                  f"- Nuestro progreso: {p['views']} / {p['min_views']} vistas ({p['clips']} clips), ETA {p['eta']}",
                  "- Mejores clips:", links, "- Texto de solicitud:", "  " + (pitch_es if es else pitch_en)]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
