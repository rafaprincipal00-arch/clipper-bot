"""Submit posted clips to Vyro campaigns from Rafa's Brave (he authorised it), without touching his tabs.

Vyro has no API and the login is Rafa's, so this drives a dedicated Brave window of its own:
- opened once with --new-window and remembered in data/vyro_window.txt;
- made invisible (alpha 1) and click-through, but kept on top so Chromium keeps rendering it
  (a window behind others is "occluded" and exposes no page content);
- driven through UI Automation + PostMessage (tiktok_brave.Brave): never the real mouse/keyboard,
  and the user's foreground window is restored after every action.

    python scripts/vyro_submit.py submit <vyro campaign url> <post url> [--dry]
    python scripts/vyro_submit.py pending      # submit every posted Vyro clip not yet submitted

Vyro only counts views gained AFTER submission, so the poster calls submit() right after posting.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import uiautomation as auto
import win32con
import win32gui

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import tiktok_brave as tb  # noqa: E402

WIN_FILE = ROOT / "data" / "vyro_window.txt"
DONE = ROOT / "data" / "vyro_submitted.json"
HOME = "https://app.vyro.com/"
# Accounts linked in Vyro, as shown in the "Social account" picker (platform suffix included).
ACCOUNTS = {"tiktok": "pepe854146 TikTok"}


def _sources() -> dict:
    """vyro campaign url -> exact campaign title shown on Vyro (sources.json `campaign`)."""
    d = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    rows = d if isinstance(d, list) else d["sources"]
    return {s["campaign_url"]: s["campaign"] for s in rows if s.get("platform") == "vyro"}


def is_vyro(campaign_url: str | None) -> bool:
    return bool(campaign_url) and "vyro.com/campaigns/" in campaign_url


def _hide(h: int) -> None:
    ex = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(h, win32con.GWL_EXSTYLE,
                           ex | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_NOACTIVATE)
    win32gui.SetLayeredWindowAttributes(h, 0, 1, win32con.LWA_ALPHA)
    tb.u.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # topmost, no move/size/activate


def window() -> tb.Brave:
    fg = tb.u.GetForegroundWindow()
    h = int(WIN_FILE.read_text()) if WIN_FILE.exists() else 0
    if not (h and tb.u.IsWindow(h) and win32gui.GetClassName(h) == "Chrome_WidgetWin_1"):
        before = tb._brave_windows()
        subprocess.Popen([tb.BRAVE, "--new-window", HOME])
        h = 0
        for _ in range(40):
            time.sleep(0.5)
            new = tb._brave_windows() - before
            if new:
                h = new.pop()
                break
        if not h:
            raise RuntimeError("Brave did not open the Vyro window")
        WIN_FILE.write_text(str(h))
    _hide(h)
    b = tb.Brave(h)
    b.user_fg = fg
    b.restore()
    return b


def _doc(b: tb.Brave):
    return b.find(lambda c: c.ControlTypeName == "DocumentControl" and c.Name.startswith("Vyro")
                  and c.BoundingRectangle.width() > 0, timeout=15)


def _press(b: tb.Brave, c) -> None:
    try:
        c.GetInvokePattern().Invoke()
    except Exception:  # noqa: BLE001 — not every node exposes Invoke
        b.click(c)
    b.restore()


def _texts(b: tb.Brave) -> list[str]:
    out = []
    for c, _ in auto.WalkControl(_doc(b), maxDepth=70):
        if (c.Name or "").strip():
            out.append(c.Name.strip())
    return out


def _esc(b: tb.Brave) -> None:
    """Start from a clean page: reload drops any open dialog (a modal hides the nav links from accessibility)."""
    rl = b.by("Button", "Volver a cargar")
    if rl is not None:
        rl.GetInvokePattern().Invoke()
        time.sleep(9)
    b.restore()


def _open_add_posts(b: tb.Brave) -> None:
    _esc(b)
    link = b.find(lambda c: c.ControlTypeName == "HyperlinkControl" and c.Name == "Add Posts"
                  and c.BoundingRectangle.width() > 0, timeout=10)
    if link is None:  # not on a Vyro page: go home through the address bar
        tb.goto(b, HOME)
        time.sleep(8)
        link = b.find(lambda c: c.ControlTypeName == "HyperlinkControl" and c.Name == "Add Posts", timeout=15)
    if link is None:
        raise RuntimeError(f"Vyro page not reachable (logged out?): {b.url()[:80]}")
    _press(b, link)
    time.sleep(8)


def _submit_button(b: tb.Brave, title: str):
    """The 'Submit post' button of the campaign card whose title is `title` (cards are in document order)."""
    current = None
    for c, _ in auto.WalkControl(_doc(b), maxDepth=70):
        n = (c.Name or "").strip()
        if c.ControlTypeName == "TextControl" and n:
            if n == title:
                current = title
            elif current and n in _sources().values():
                current = None
        if c.ControlTypeName == "ButtonControl" and n == "Submit post" and current == title:
            return c
    return None


def submit(campaign_url: str, post_url: str, platform: str = "tiktok", dry: bool = False) -> str:
    title = _sources().get(campaign_url)
    if not title:
        raise RuntimeError(f"unknown Vyro campaign {campaign_url}")
    done = json.loads(DONE.read_text(encoding="utf-8")) if DONE.exists() else {}
    if post_url in done:
        return "already submitted"
    b = window()
    _open_add_posts(b)
    btn = _submit_button(b, title)
    if btn is None:
        raise RuntimeError(f"campaign '{title}' not in My campaigns (not joined or ended)")
    _press(b, btn)
    time.sleep(5)
    pick = b.find(lambda c: c.Name == "Select social account" and c.BoundingRectangle.width() > 0, timeout=10)
    b.click(pick)
    time.sleep(2)
    acct = b.find(lambda c: c.ControlTypeName == "ButtonControl" and c.Name == ACCOUNTS[platform], timeout=8)
    if acct is None:
        raise RuntimeError(f"{ACCOUNTS[platform]} not linked in Vyro")
    _press(b, acct)
    time.sleep(3)
    _press(b, b.find(lambda c: c.ControlTypeName == "ButtonControl" and c.Name == "Use a link instead", timeout=8))
    time.sleep(2)
    box = b.find(lambda c: c.ControlTypeName == "EditControl" and c.BoundingRectangle.width() > 0
                 and "Barra de direcciones" not in c.Name, timeout=8)
    if box is None:
        raise RuntimeError("link field not found")
    b.click(box)
    time.sleep(0.3)
    b.chars(post_url, delay=0.01)
    time.sleep(1)
    rules = b.find(lambda c: c.ControlTypeName == "CheckBoxControl" and "campaign rules" in c.Name, timeout=5)
    if rules is not None and rules.GetTogglePattern().ToggleState != 1:
        b.click(rules)
    time.sleep(1)
    typed = box.GetValuePattern().Value
    if dry:
        _esc(b)  # reload: closes the form without submitting
        return f"dry run ok (link field = {typed!r})"
    _press(b, b.find(lambda c: c.ControlTypeName == "ButtonControl" and c.Name in ("Continue", "Submit"), timeout=5))
    time.sleep(6)
    for _ in range(2):  # a confirmation step may follow
        nxt = b.find(lambda c: c.ControlTypeName == "ButtonControl" and c.Name in ("Submit", "Submit post", "Confirm")
                     and c.BoundingRectangle.width() > 0 and c != btn, timeout=3)
        if nxt is None:
            break
        _press(b, nxt)
        time.sleep(6)
    page = " | ".join(_texts(b))
    err = next((t for t in ("already been submitted", "Something’s not right", "Invalid", "not found", "error")
                if t.lower() in page.lower()), None)
    status = f"error: {err}" if err else "submitted"
    if not err:
        done[post_url] = {"campaign": title, "at": time.strftime("%Y-%m-%d %H:%M")}
        DONE.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
    b.restore()
    return status


def pending(log=print) -> None:
    """Every posted TikTok clip of a Vyro campaign that is not submitted yet (retries after a failure)."""
    plan = json.loads((ROOT / "data" / "tiktok_plan.json").read_text(encoding="utf-8"))
    done = json.loads(DONE.read_text(encoding="utf-8")) if DONE.exists() else {}
    for it in plan.get("items", []):
        if it.get("status") == "posted" and is_vyro(it.get("campaign")) and it.get("url") not in done:
            try:
                log(f"  Vyro submit {it['url']}: {submit(it['campaign'], it['url'])}")
            except Exception as e:  # noqa: BLE001 — retried on the next pass
                log(f"  Vyro submit FAILED {it['url']}: {e}")


if __name__ == "__main__":
    if sys.argv[1] == "submit":
        print(submit(sys.argv[2], sys.argv[3], dry="--dry" in sys.argv))
    elif sys.argv[1] == "pending":
        pending()
