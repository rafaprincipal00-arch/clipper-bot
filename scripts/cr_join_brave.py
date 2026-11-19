"""Join Content Rewards campaigns from the hidden bot window in Rafa's Brave (his logged-in CR session),
for when the CR_STATE secret used by cr_join.yml has expired. Prints the unlocked brief per campaign.

    python scripts/cr_join_brave.py <uuid> [<uuid> ...]     (one hidden window per campaign)
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subprocess  # noqa: E402

import tiktok_brave as tb  # noqa: E402
import uiautomation as auto  # noqa: E402
import vyro_submit as vs  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
JOIN = re.compile(r"^(Join Campaign|Unirse a la campaña|Unirse|Join)$", re.I)


def texts(b) -> list[str]:
    out = []
    for d in b.all(lambda c: c.ControlTypeName == "DocumentControl" and c.BoundingRectangle.width() > 100):
        for c, _ in auto.WalkControl(d, maxDepth=80):
            nm = (c.Name or "").strip()
            if nm and c.ControlTypeName in ("TextControl", "ButtonControl", "HyperlinkControl"):
                out.append(nm)
    return out


def open_hidden(url: str) -> "tb.Brave":
    fg = tb.u.GetForegroundWindow()
    before = tb._brave_windows()
    subprocess.Popen([tb.BRAVE, "--new-window", url])
    h = 0
    for _ in range(40):
        time.sleep(0.5)
        new = tb._brave_windows() - before
        if new:
            h = new.pop()
            break
    vs._hide(h)
    b = tb.Brave(h)
    b.user_fg = fg
    b.restore()
    time.sleep(12)
    dismiss_popups(b)
    return b


POPUP = re.compile(r"^(Ahora no|Not now|Maybe later|Más tarde|Got it|Entendido)$", re.I)


def dismiss_popups(b) -> None:
    """CR shows promo modals ("Soporte ya está aquí" / "Support is here") over the campaign page; while
    open, UIA sees only the modal and the Join/Submit buttons look missing."""
    for _ in range(3):
        btns = b.all(lambda c: c.ControlTypeName == "ButtonControl" and POPUP.match((c.Name or "").strip())
                     and c.BoundingRectangle.width() > 0)
        if not btns:
            return
        try:
            btns[0].GetInvokePattern().Invoke()
        except Exception:  # noqa: BLE001
            b.click(btns[0])
        b.restore()
        time.sleep(2)


def main() -> None:
    res = {}
    for cid in sys.argv[1:]:
        b = open_hidden(f"https://contentrewards.com/c/campaigns/{cid}")  # omnibox goto doesn't navigate
        btns = [c for c in b.all(lambda c: c.ControlTypeName in ("ButtonControl", "HyperlinkControl")
                                 and JOIN.match((c.Name or "").strip()) and c.BoundingRectangle.width() > 0)]
        joined = False
        if btns:
            x = btns[0]
            try:
                x.GetInvokePattern().Invoke()
            except Exception:  # noqa: BLE001
                b.click(x)
            b.restore()
            time.sleep(7)
            # a confirm dialog may follow
            for c in b.all(lambda c: c.ControlTypeName == "ButtonControl" and JOIN.match((c.Name or "").strip())
                           and c.BoundingRectangle.width() > 0)[-1:]:
                try:
                    c.GetInvokePattern().Invoke()
                except Exception:  # noqa: BLE001
                    b.click(c)
                b.restore()
                time.sleep(6)
        t = texts(b)
        joined = not any(JOIN.match(x) for x in t) and any(re.search(r"Submit clip|Enviar clip|Enviar", x) for x in t)
        res[cid] = {"joined": joined, "had_button": bool(btns), "url": b.url()}
        print("=====", cid, "button:", bool(btns), "JOINED:", joined, flush=True)
        txt = "\n".join(t)
        i = max(txt.find("Brief"), txt.find("Materiales"), 0)
        print(txt[i:i + 1800], flush=True)
        b.close()
    print(json.dumps(res))


if __name__ == "__main__":
    main()
