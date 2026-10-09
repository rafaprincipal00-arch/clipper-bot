"""Scan Content Rewards campaigns with our logged-in session and write data/cr_scan.json (read-only).

For every campaign card reachable from Discover (scrolled to the end) it opens the campaign page and keeps
the facts that decide whether a campaign is worth clipping: status, CPM per platform, min/max payout,
budget left, number of clippers, total approved views, top clipper earnings, requirements text.
Run by .github/workflows/cr_scan.yml (the CR_STATE session only exists in GitHub Actions).
"""
import json
import os
import re
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cr_scan.json"
MAX_CAMPAIGNS = int(os.environ.get("CR_SCAN_MAX", "120"))


def _money(s: str) -> float | None:
    m = re.search(r"\$([\d,.]+)\s*([kKmM]?)", s or "")
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1)


def _after(text: str, label: str, n: int = 1) -> str:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    for i, x in enumerate(lines):
        if x == label and i + n < len(lines):
            return lines[i + n]
    return ""


def parse(url: str, text: str) -> dict:
    body = text.split("Connect Discord", 1)[-1]
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    title = lines[3] if len(lines) > 3 else ""
    platforms = {}
    for p in ("TikTok", "Instagram", "YouTube", "X", "Facebook"):
        m = re.search(rf"\n{p}\n+Per 1K views\n+\$([\d.]+)\n+Min payout\n+\$([\d.,]+)\n+Max payout\n+\$([\d.,]+)", body)
        if m:
            platforms[p] = {"cpm": float(m.group(1)), "min": float(m.group(2).replace(",", "")),
                            "max": float(m.group(3).replace(",", ""))}
    status = next((s for s in ("Active", "Paused", "Ended", "Scheduled", "Completed") if f"\n{s}\n" in body), "?")
    req = ""
    if "Reference materials" in body:
        req = body.split("Reference materials", 1)[1].split("Top clippers", 1)[0].strip()[:1500]
    top = re.findall(r"Rank\n+1 / (\d+)\n+(.+)\n+(\$[\d.,]+k?)", body)
    views = re.search(r"\n([\d.]+[KMB]?)\nviews\n+Views across every approved clip", body)
    rem = re.search(r"\$[\d,.]+[kK]?\S* remaining", body)
    return {"url": url, "title": title, "brand": lines[2] if len(lines) > 2 else "", "status": status,
            "platforms": platforms, "budget": _money(_after(body, "Budget")),
            "remaining": _money(rem.group(0)) if rem else None,
            "clippers": int(top[0][0]) if top else None, "top_clipper": top[0][2] if top else None,
            "approved_views": views.group(1) if views else None,
            "application": "Application" in body.split("Reference materials", 1)[0][-400:] or "Apply" in body[:3000],
            "out_of_budget": "Out of budget" in body, "requirements": req, "joined": "Submit clip" in body}


def main() -> None:
    state = os.environ["CR_STATE"]
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        sf = Path(tmp) / "state.json"
        sf.write_text(state, encoding="utf-8")
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(sf), viewport={"width": 1400, "height": 1000}, locale="en-US")
        page = ctx.new_page()
        page.goto("https://contentrewards.com/c/discover", wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        if "/login" in page.url:
            raise SystemExit("SESSION EXPIRED")
        links: list[str] = []
        for _ in range(40):  # infinite scroll on "All campaigns"
            found = page.eval_on_selector_all("a[href*='/c/campaigns/']", "els => els.map(e => e.href.split('?')[0])")
            new = [u for u in dict.fromkeys(found) if u not in links]
            links += new
            page.mouse.wheel(0, 6000)
            page.wait_for_timeout(1500)
            if not new and _ > 8:
                break
        print(f"{len(links)} campaigns")
        out = []
        for url in links[:MAX_CAMPAIGNS]:
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
                out.append(parse(url, page.inner_text("body")))
            except Exception as e:  # noqa: BLE001 — one bad page must not stop the scan
                out.append({"url": url, "error": str(e)[:200]})
        # Our own submissions with their per-clip state.
        page.goto("https://contentrewards.com/c/discover", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        page.get_by_role("link", name="Submissions", exact=True).first.evaluate("el => el.click()")
        page.wait_for_timeout(9000)
        subs = page.inner_text("body").split("Connect Discord", 1)[-1][:8000]
        browser.close()
    OUT.write_text(json.dumps({"campaigns": out, "submissions_page": subs}, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
