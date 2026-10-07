"""Publish one clip on TikTok through the user's own Brave (TikTok Studio web), fully in the background.

Works in a NEW TAB of the user's already-open Brave window (his session, no extra windows or profiles),
driven through UI Automation + PostMessage (never the real mouse/keyboard). The user's previous tab is
re-selected and the bot's tab closed at the end; his foreground window gets focus back after every step.

Flow: upload file -> TikTok editor: add a song from TikTok's licensed library at -12 dB with fade-out ->
caption + hashtags -> wait for the content check -> Publicar -> read the public video URL.
"""
import ctypes
import ctypes.wintypes as w
import random
import subprocess
import time
from pathlib import Path

import uiautomation as auto
import win32gui

BRAVE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
UPLOAD = "https://www.tiktok.com/tiktokstudio/upload"
HANDLES = {1: "pepe854146", 2: "streammoments.daily", 3: "rafael.benitez656"}
# Songs from assets/music/WISHLIST.md, added from TikTok's own library (licensed there, never embedded).
SONGS = {
    "hype": [("PASSO BEM SOLTO", "ATLXS"), ("FUNK ABNORMAL", "DJ V12"), ("HOTEL LOBBY", "Quavo")],
    "chaos": [("Sweet Dreams - Slowed + Reverb", "Ravens Rock"), ("FUNK ABNORMAL", "DJ V12")],
    "drama": [("Can You Feel My Heart", "Bring Me The Horizon"), ("Raya", "Zericxxn")],
    "sus": [("Distractions", "Haiti Babii"), ("Raya", "Zericxxn")],
    "funny": [("Golden Brown", "The Stranglers"), ("Just The Two Of Us", "Grover Washington")],
    "awkward": [("Golden Brown", "The Stranglers"), ("Distractions", "Haiti Babii")],
    "chill": [("She Knows", "J. Cole"), ("In the Air 2", "babysevin")],
}
MUSIC_DB = "-12"

u = ctypes.windll.user32
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


class Brave:
    def __init__(self, hwnd: int):
        self.h = hwnd
        self.user_fg = u.GetForegroundWindow()

    # ---- focus hygiene: the user keeps working on the other monitor ----
    def restore(self) -> None:
        fg = u.GetForegroundWindow()
        if self.user_fg and fg != self.user_fg and u.IsWindow(self.user_fg):
            t1 = u.GetWindowThreadProcessId(fg, None)
            t2 = ctypes.windll.kernel32.GetCurrentThreadId()
            u.AttachThreadInput(t2, t1, True)
            u.SetForegroundWindow(self.user_fg)
            u.AttachThreadInput(t2, t1, False)

    # ---- UIA lookups ----
    def root(self):
        c = auto.ControlFromHandle(self.h)
        if c is None:
            raise RuntimeError("Brave window is gone")
        return c

    def find(self, pred, timeout: float = 0, depth: int = 70):
        end = time.time() + timeout
        while True:
            for c, _ in auto.WalkControl(self.root(), maxDepth=depth):
                try:
                    if pred(c):
                        return c
                except Exception:  # noqa: BLE001 — nodes vanish while the page changes
                    continue
            if time.time() >= end:
                return None
            time.sleep(1)

    def all(self, pred, depth: int = 70) -> list:
        out = []
        for c, _ in auto.WalkControl(self.root(), maxDepth=depth):
            try:
                if pred(c):
                    out.append(c)
            except Exception:  # noqa: BLE001
                continue
        return out

    def by(self, kind: str, name: str, timeout: float = 0, starts: bool = False):
        t = kind + "Control"
        return self.find(lambda c: c.ControlTypeName == t and c.BoundingRectangle.width() > 0
                         and (c.Name.startswith(name) if starts else c.Name == name), timeout)

    def url(self) -> str:
        bar = self.by("Edit", "Barra de direcciones", starts=True)
        return bar.GetValuePattern().Value if bar else ""

    # ---- input via PostMessage to the page (no real mouse/keyboard) ----
    def _render(self) -> int:
        res = []
        win32gui.EnumChildWindows(self.h, lambda h, _: res.append(h) if win32gui.GetClassName(h) ==
                                  "Chrome_RenderWidgetHostHWND" and win32gui.IsWindowVisible(h) else None, None)
        return res[0]

    def click(self, c=None, x: int | None = None, y: int | None = None) -> None:
        if c is not None:
            r = c.BoundingRectangle
            x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        rh = self._render()
        cx, cy = win32gui.ScreenToClient(rh, (x, y))
        lp = (cy << 16) | (cx & 0xFFFF)
        u.PostMessageW(rh, 0x0200, 0, lp)
        u.PostMessageW(rh, 0x0201, 1, lp)
        time.sleep(0.05)
        u.PostMessageW(rh, 0x0202, 0, lp)
        self.restore()

    def key(self, vk: int, times: int = 1) -> None:
        rh = self._render()
        sc = u.MapVirtualKeyW(vk, 0)
        for _ in range(times):
            u.PostMessageW(rh, 0x0100, vk, 1 | (sc << 16))
            time.sleep(0.02)
            u.PostMessageW(rh, 0x0101, vk, 1 | (sc << 16) | (0xC0 << 24))
            time.sleep(0.02)

    def chars(self, text: str, delay: float = 0.03) -> None:
        rh = self._render()
        for ch in text:
            u.PostMessageW(rh, 0x0102, ord(ch), 1)
            time.sleep(delay)

    def wheel(self, x: int, y: int, notches: int) -> None:
        rh = self._render()
        for _ in range(abs(notches)):
            d = 120 if notches > 0 else -120
            u.PostMessageW(rh, 0x020A, (d & 0xFFFF) << 16, (y << 16) | x)
            time.sleep(0.15)

    def set_number(self, edit, value: str) -> str:
        self.click(edit)
        time.sleep(0.3)
        self.key(0x23)  # End
        self.key(0x08, 6)  # Backspace
        self.chars(value)
        self.key(0x0D)
        time.sleep(0.8)
        return edit.GetValuePattern().Value

    def selected_tab(self):
        for c in self.all(lambda c: c.ControlTypeName == "TabItemControl", depth=20):
            try:
                if c.GetSelectionItemPattern().IsSelected:
                    return c
            except Exception:  # noqa: BLE001
                continue
        return None

    def close(self) -> None:
        """Close the bot's tab and give the user his previous tab back."""
        tab = self.selected_tab()
        if tab is not None and tab.Name != getattr(self, "user_tab", None):
            btn = tab.ButtonControl(Name="Cerrar")
            if btn.Exists(1):
                try:
                    btn.GetInvokePattern().Invoke()
                except Exception:  # noqa: BLE001
                    self.click(btn)
            time.sleep(1)
        prev = getattr(self, "user_tab", None)
        if prev:
            for c in self.all(lambda c: c.ControlTypeName == "TabItemControl" and c.Name == prev, depth=20):
                try:
                    c.GetSelectionItemPattern().Select()
                except Exception:  # noqa: BLE001
                    pass
                break
        self.restore()


def _brave_windows() -> set[int]:
    res = set()

    @EnumProc
    def cb(h, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, cls, 64)
        if cls.value == "Chrome_WidgetWin_1" and u.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(300)
            u.GetWindowTextW(h, t, 300)
            if t.value.endswith("Brave"):
                res.add(h)
        return True

    u.EnumWindows(cb, 0)
    return res


def user_window() -> int:
    """The user's open Brave window (default profile). Raises if Brave is not open."""
    wins = _brave_windows()
    if not wins:
        raise RuntimeError("Brave is not open")
    # Most recently used = highest in z-order among Brave windows.
    h = u.GetTopWindow(0)
    while h:
        if h in wins:
            return h
        h = u.GetWindow(h, 2)  # GW_HWNDNEXT
    return wins.pop()


def open_tab(url: str = UPLOAD) -> Brave:
    """New tab in the user's existing Brave window; focus goes straight back to whatever he was using."""
    fg = u.GetForegroundWindow()
    h = user_window()
    b = Brave(h)
    b.user_fg = fg
    prev = b.selected_tab()
    b.user_tab = prev.Name if prev is not None else None
    before = len(b.all(lambda c: c.ControlTypeName == "TabItemControl", depth=20))
    subprocess.Popen([BRAVE, url])  # Brave opens it as a tab in its last active window
    for _ in range(40):
        time.sleep(0.5)
        b.restore()
        if len(b.all(lambda c: c.ControlTypeName == "TabItemControl", depth=20)) > before:
            break
    else:
        raise RuntimeError("Brave did not open the tab")
    b.restore()
    return b


def _file_dialog(path: str, timeout: float = 20) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        found = []

        @EnumProc
        def cb(h, _):
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(h, cls, 64)
            if cls.value == "#32770" and u.IsWindowVisible(h):
                found.append(h)
            return True

        u.EnumWindows(cb, 0)
        if found:
            dlg = found[0]
            e = u.FindWindowExW(dlg, 0, "ComboBoxEx32", None)
            e = u.FindWindowExW(e, 0, "ComboBox", None)
            e = u.FindWindowExW(e, 0, "Edit", None)
            u.SendMessageW(e, 0x0C, 0, ctypes.c_wchar_p(path))
            time.sleep(0.3)
            u.SendMessageW(dlg, 0x111, 1, 0)
            time.sleep(1.5)
            return not u.IsWindow(dlg)
        time.sleep(0.5)
    return False


def _dismiss(b: Brave) -> None:
    for name in ("Entendido", "Activar", "Got it", "Turn on"):
        btn = b.by("Button", name)
        if btn:
            b.click(btn)
            time.sleep(1)


def add_music(b: Brave, mood: str, log=print) -> str | None:
    """Open TikTok's editor, add the first available song for this mood at -12 dB, save. Returns the song."""
    sounds = b.find(lambda c: c.ControlTypeName == "ButtonControl" and c.Name == "Sonidos"
                    and c.BoundingRectangle.width() > 0, timeout=30)
    if not sounds:
        log("  music: no 'Sonidos' button, posting with original audio")
        return None
    b.click(sounds)
    search = b.by("Edit", "Buscar sonidos", timeout=40)
    if not search:
        log("  music: editor did not open")
        return None
    time.sleep(2)
    _dismiss(b)
    options = SONGS.get(mood, []) + [s for m in SONGS.values() for s in m]
    for title, artist in options:
        b.click(search)
        time.sleep(0.3)
        clear = b.by("Button", "Clear input")
        if clear:
            b.click(clear)
            time.sleep(0.5)
            b.click(search)
        b.chars(f"{title} {artist}")
        b.key(0x0D)
        time.sleep(5)
        items = b.all(lambda c: c.ControlTypeName == "ListItemControl" and c.BoundingRectangle.width() > 0
                      and c.BoundingRectangle.left < 600 and title.lower() in c.Name.lower())
        if not items:
            continue
        r = items[0].BoundingRectangle
        b.click(x=r.right - 27, y=(r.top + r.bottom) // 2)  # the "+" of the row
        time.sleep(3)
        _dismiss(b)
        db = b.by("Edit", "dB", timeout=10)
        if not db:
            continue
        b.set_number(db, MUSIC_DB)
        fades = sorted(b.all(lambda c: c.ControlTypeName == "EditControl" and c.Name == "s"
                             and c.BoundingRectangle.width() > 0), key=lambda c: c.BoundingRectangle.top)
        if len(fades) >= 2:
            b.set_number(fades[-1], "1")
        b.click(b.by("Button", "Guardar", timeout=5))
        time.sleep(10)
        log(f"  music: {title} - {artist} at {MUSIC_DB} dB")
        return f"{title} - {artist}"
    log("  music: none of the songs found; closing editor")
    cancel = b.by("Button", "Cancelar")
    if cancel:
        b.click(cancel)
        time.sleep(3)
    return None


def set_caption(b: Brave, stem: str, caption: str) -> None:
    b.wheel(800, 500, 12)  # scroll to the top of the form
    time.sleep(1.5)
    desc = b.find(lambda c: c.ControlTypeName == "TextControl" and c.Name == stem
                  and c.BoundingRectangle.width() > 0, timeout=20)
    if not desc:
        raise RuntimeError("caption box not found")
    r = desc.BoundingRectangle
    b.click(x=r.right - 2, y=(r.top + r.bottom) // 2)
    time.sleep(0.4)
    b.key(0x23)
    b.key(0x08, len(stem) + 10)
    time.sleep(0.4)
    words = caption.replace("\n", " ").split(" ")
    text = [x for x in words if x and not x.startswith("#")]
    tags = [x for x in words if x.startswith("#")]
    b.chars(" ".join(text) + " ")
    for tag in tags:
        b.chars(tag)
        time.sleep(1.5)  # hashtag suggestion pops up; a space closes it
        b.chars(" ")
        time.sleep(0.6)


def wait_checks(b: Brave, minutes: float = 12) -> str:
    end = time.time() + minutes * 60
    while time.time() < end:
        ok = b.find(lambda c: c.ControlTypeName == "TextControl" and c.Name.startswith("No se han detectado"))
        if ok:
            return "ok"
        bad = b.find(lambda c: c.ControlTypeName == "TextControl" and ("infring" in c.Name.lower() and
                                                                           c.Name.startswith("Se ")))
        if bad:
            return "warning: " + bad.Name[:120]
        time.sleep(15)
    return "timeout"


def publish(b: Brave, caption_start: str, handle: str) -> str:
    b.wheel(800, 600, -12)
    time.sleep(1)
    b.click(b.by("Button", "Publicar", timeout=10))
    for _ in range(40):
        time.sleep(3)
        for name in ("Publicar ahora", "Post now"):
            btn = b.by("Button", name)
            if btn:
                b.click(btn)
        if "tiktokstudio/content" in b.url():
            break
    else:
        raise RuntimeError("TikTok did not confirm the post")
    for _ in range(12):
        time.sleep(10)
        for c in b.all(lambda c: c.ControlTypeName == "HyperlinkControl"):
            try:
                v = c.GetValuePattern().Value
            except Exception:  # noqa: BLE001
                continue
            if f"/@{handle}/video/" in v and c.Name.startswith(caption_start[:25]):
                return v.split("?")[0]
    raise RuntimeError("posted, but the video link did not show up in TikTok Studio")


def active_handle(b: Brave) -> str | None:
    """@handle of the TikTok account logged in (from the avatar menu's Perfil link)."""
    avatar = b.find(lambda c: c.ControlTypeName == "ButtonControl" and not c.Name and c.BoundingRectangle.width() > 0
                    and c.BoundingRectangle.top < 150 and c.BoundingRectangle.left > b.root().BoundingRectangle.right - 120,
                    timeout=20)
    if not avatar:
        return None
    b.click(avatar)
    link = b.by("Hyperlink", "Perfil", timeout=5)
    handle = None
    if link:
        v = link.GetValuePattern().Value
        handle = v.split("/@", 1)[1].split("?")[0] if "/@" in v else None
    b.click(x=b.root().BoundingRectangle.left + 900, y=b.root().BoundingRectangle.top + 900)  # close menu
    return handle


def post(account: int, video: Path, caption: str, mood: str = "hype", log=print) -> dict:
    """Full flow for one clip. Returns {"url", "music", "check"}."""
    b = open_tab()
    try:
        time.sleep(4)
        if "login" in b.url():
            raise RuntimeError("TikTok is not logged in in Brave")
        if active_handle(b) != HANDLES[account]:
            raise RuntimeError(f"Brave is logged into @{active_handle(b)}, not @{HANDLES[account]}")
        btn = b.by("Button", "Seleccionar vídeo", timeout=60)
        if not btn:
            raise RuntimeError("upload page did not load")
        b.click(btn)
        if not _file_dialog(str(video)):
            raise RuntimeError("file dialog did not accept the clip")
        time.sleep(8)
        _dismiss(b)
        music = add_music(b, mood, log)
        _dismiss(b)
        set_caption(b, video.stem, caption)
        check = wait_checks(b)
        log(f"  content check: {check}")
        if check.startswith("warning"):
            raise RuntimeError(f"TikTok flagged the clip: {check}")
        first = " ".join(x for x in caption.split() if not x.startswith("#"))
        url = publish(b, first, HANDLES[account])
        return {"url": url, "music": music, "check": check}
    finally:
        time.sleep(random.uniform(1, 3))
        b.close()
        b.restore()
