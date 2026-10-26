"""Drive a HIDDEN bot window inside Rafa's Brave (his logged-in sessions, never his tabs, mouse or keyboard).

    python scripts/bot_window.py <name> open <url>        # new hidden window, remembered in data/win_<name>.txt
    python scripts/bot_window.py <name> dump [n]          # URL + buttons/links/texts/edits
    python scripts/bot_window.py <name> click <prefix> [nth] [ControlType] [wait_s]
    python scripts/bot_window.py <name> type <edit-prefix> <text>
    python scripts/bot_window.py <name> text <substring>
    python scripts/bot_window.py <name> close

The window is alpha=1, click-through and topmost (an occluded window exposes no page content to UIA).
Close it as soon as the step ends: links Rafa opens from other apps can land in it, invisible to him.
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tiktok_brave as tb  # noqa: E402
import uiautomation as auto  # noqa: E402
import vyro_submit as vs  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
KINDS = ("ButtonControl", "HyperlinkControl", "ListItemControl", "TextControl", "CheckBoxControl",
         "RadioButtonControl", "MenuItemControl", "TabItemControl", "ComboBoxControl")


def dump(b, n=120):
    out = []
    for d in b.all(lambda c: c.ControlTypeName == "DocumentControl" and c.BoundingRectangle.width() > 100):
        for c, _ in auto.WalkControl(d, maxDepth=80):
            nm = (c.Name or "").strip()
            if (nm and c.ControlTypeName in KINDS) or c.ControlTypeName == "EditControl":
                v = ""
                if c.ControlTypeName == "EditControl":
                    try:
                        v = " = " + c.GetValuePattern().Value[:80]
                    except Exception:  # noqa: BLE001
                        pass
                out.append(f"{c.ControlTypeName[:-7]}: {nm[:140]}{v}")
    print("URL", b.url())
    print("\n".join(out[:n]))


def find(b, name, nth=0, kind=None):
    xs = b.all(lambda c: c.BoundingRectangle.width() > 0
               and (c.ControlTypeName == kind if kind else c.ControlTypeName in KINDS + ("EditControl",))
               and (c.Name or "").strip().startswith(name))
    print("matches", len(xs))
    return xs[nth] if len(xs) > nth else None


def main() -> None:
    name, cmd, args = sys.argv[1], sys.argv[2], sys.argv[3:]
    f = DATA / f"win_{name}.txt"
    if cmd == "open":
        fg = tb.u.GetForegroundWindow()
        before = tb._brave_windows()
        subprocess.Popen([tb.BRAVE, "--new-window", args[0]])
        h = 0
        for _ in range(40):
            time.sleep(0.5)
            new = tb._brave_windows() - before
            if new:
                h = new.pop()
                break
        if not h:
            sys.exit("no new Brave window")
        vs._hide(h)
        f.write_text(str(h))
        b = tb.Brave(h)
        b.user_fg = fg
        b.restore()
        time.sleep(10)
        dump(b, int(args[1]) if len(args) > 1 else 60)
        b.restore()
        return
    b = tb.Brave(int(f.read_text()))
    b.user_fg = tb.u.GetForegroundWindow()
    if cmd == "close":
        b.close()
        f.unlink(missing_ok=True)
        print("closed", name)
        return
    if cmd == "click":
        x = find(b, args[0], int(args[1]) if len(args) > 1 else 0, args[2] if len(args) > 2 else None)
        if x is None:
            print("NOT FOUND")
        else:
            try:
                if x.ControlTypeName not in ("ButtonControl", "HyperlinkControl", "MenuItemControl"):
                    raise RuntimeError
                x.GetInvokePattern().Invoke()
            except Exception:  # noqa: BLE001
                b.click(x)
            b.restore()
            time.sleep(float(args[3]) if len(args) > 3 else 6)
    elif cmd == "type":
        x = find(b, args[0], 0, "EditControl")
        b.click(x)
        time.sleep(0.4)
        b.key(0x23)
        b.key(0x08, 60)
        b.chars(args[1])
        time.sleep(1)
    elif cmd == "text":
        for d in b.all(lambda c: c.ControlTypeName == "DocumentControl" and c.BoundingRectangle.width() > 100):
            for c, _ in auto.WalkControl(d, maxDepth=80):
                if args[0].lower() in (c.Name or "").lower():
                    print(c.ControlTypeName, "|", c.Name[:300])
        b.restore()
        return
    dump(b, int(args[0]) if cmd == "dump" and args else 90)
    b.restore()


if __name__ == "__main__":
    main()
