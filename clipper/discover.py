"""Discover live clipping campaigns and rank the best-paying streamer ones.

Source: contentrewards.com/discover (Whop Content Rewards marketplace), which
server-renders the campaign list as JSON inside the page.
"""
import json
import re
import sys
import urllib.request
from html import unescape
from pathlib import Path

DISCOVER_URL = "https://contentrewards.com/discover"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
STREAM_WORDS = re.compile(r"stream|twitch|kick|livestream|vod|gaming|podcast|youtube|interview|clipping", re.I)
SKIP_TYPES = re.compile(r"slideshow|UGC|logo|song|music|AI slideshow", re.I)
NON_ENGLISH = re.compile(r"\[(FRANCE|FR|DEUTSCH|ES|ESP|ARABIC)\]|\(Deutsch\)|habla|clippe|gana dinero|campaña|اصنع", re.I)


def fetch_html(url: str = DISCOVER_URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "ignore")


def parse_campaigns(html: str) -> list[dict]:
    text = html.replace('\\\\"', "'").replace('\\"', '"')
    out = []
    for m in re.finditer(r'\{"availableBudgetRaw":([\d.]+)', text):
        seg = text[m.start(): m.start() + 6000]
        cut = seg.find('"thumbnailBlur"')
        seg = seg[:cut] if cut > 0 else seg

        def field(key: str, pat: str = r'"([^"]*)"'):
            mm = re.search('"' + key + '":' + pat, seg)
            return mm.group(1) if mm else None

        platforms = field("platforms", r"\[([^\]]*)\]") or ""
        out.append({
            "id": field("id"),
            "title": field("title"),
            "brand": field("brand"),
            "category": field("category"),
            "description": (field("description") or "").replace("\\\\n", " ").strip(),
            "cpm": float(field("payoutSortRaw", r"([\d.]+)") or 0),
            "budget_left": float(m.group(1)),
            "budget_total": float(field("budgetTotalRaw", r"([\d.]+)") or 0),
            "platforms": re.findall(r'"(\w+)"', platforms),
            "requires_application": field("requiresApplication", r"(true|false)") == "true",
            "clippers": int(field("creatorCountRaw", r"(\d+)") or 0),
            "url": f"https://contentrewards.com/discover/{field('id')}",
        })
    return [c for c in out if c["id"]]


def score(c: dict) -> float:
    # Rate matters, but a high CPM with no budget left pays nothing.
    depth = min(c["budget_left"], 20000) / 20000
    crowd = 1 / (1 + c["clippers"] / 300)
    return c["cpm"] * (0.25 + depth) * (0.5 + crowd)


def rank(campaigns: list[dict], top: int = 15, streamers_only: bool = True) -> list[dict]:
    pool = [c for c in campaigns if c["budget_left"] >= 300 and c["cpm"] > 0]
    pool = [c for c in pool if not NON_ENGLISH.search(f"{c['title']} {c['description']}")]
    if streamers_only:
        pool = [c for c in pool if STREAM_WORDS.search(f"{c['title']} {c['description']} {c['category']}")
                and not SKIP_TYPES.search(f"{c['title']} {c['description']}")]
    for c in pool:
        c["score"] = round(score(c), 3)
    return sorted(pool, key=lambda c: -c["score"])[:top]


def enrich(c: dict) -> dict:
    """Campaign page: min/max payout, content rules and reference (source) links."""
    try:
        html = fetch_html(c["url"])
    except OSError as e:
        c["detail_error"] = str(e)
        return c
    text = re.sub(r"(?s)<(script|style).*?</\1>", "", html)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    m = re.search(r"Min payout \$([\d,.]+) Max payout \$([\d,.]+)", text)
    if m:
        c["min_payout"], c["max_payout"] = (float(x.replace(",", "")) for x in m.groups())
    m = re.search(r"Content requirements (.*?)(?: Top clippers| Views across|$)", text)
    c["requirements"] = unescape(m.group(1).strip()[:800]) if m else ""
    links = re.findall(r'href="(https?://[^"]+)"[^>]*rel="noopener noreferrer" target="_blank"', html)
    c["reference_links"] = sorted({unescape(l) for l in links
                                   if "contentrewards" not in l and "linkedin" not in l})
    c["sources"] = [l for l in c["reference_links"] if VIDEO_SOURCE.search(l)]
    return c


VIDEO_SOURCE = re.compile(r"youtube\.com/@|youtube\.com/(c|channel)/|twitch\.tv/(?!videos)|kick\.com/|youtu\.be/|twitch\.tv/videos/")


def build_sources(top: list[dict], path: Path) -> None:
    """Merge campaign video sources into config/sources.json, keeping manual edits."""
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    known = {s["source"] for s in existing}
    for c in top:
        for src in c.get("sources", []):
            if src in known:
                continue
            existing.append({
                "creator": c["brand"] or c["title"], "source": src, "campaign": c["title"],
                "campaign_url": c["url"], "cpm": c["cpm"], "enabled": not c["requires_application"],
                "hashtags": [], "credit": "", "requirements": c.get("requirements", ""),
            })
            known.add(src)
    path.write_text(json.dumps(existing, indent=1, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/campaigns.json")
    campaigns = parse_campaigns(fetch_html())
    ranked = [enrich(c) for c in rank(campaigns)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"all": campaigns, "top": ranked}, indent=1, ensure_ascii=False), encoding="utf-8")
    build_sources(ranked, Path(__file__).resolve().parent.parent / "config" / "sources.json")
    print(f"{len(campaigns)} campaigns, top {len(ranked)}:")
    for c in ranked:
        print(f"  ${c['cpm']:.2f}/1K  left ${c['budget_left']:>8.0f}  {c['title']}")


if __name__ == "__main__":
    main()
