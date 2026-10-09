"""Sign the bot's hidden TikTok profiles in by QR, without the bot touching the user's browser.

The bot's own headless Chromium (profile data/tt_profiles/<n>) opens TikTok's QR login. This script serves
that QR on http://127.0.0.1:8777 — the only thing that goes to the user's Brave is that one local page,
which shows which account to switch to in the TikTok app and the live QR. The user scans it on the phone;
the session cookies land in the bot's profile. One account after another.

    python scripts/tiktok_qr_login.py          # all accounts not yet signed in
    python scripts/tiktok_qr_login.py 2 3      # only these
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, __import__("os").path.dirname(__file__))
from tiktok_bg import HANDLES, _ctx, _signed_in  # noqa: E402

PORT = 8777
QR_URL = "https://www.tiktok.com/login/qrcode"
STATE = {"account": None, "handle": None, "png": b"", "status": "Arrancando…", "done": [], "finished": False}

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Login TikTok del bot</title>
<style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;flex-direction:column;align-items:center;padding:30px;gap:14px}
h1{font-size:22px;margin:0}.acc{font-size:30px;font-weight:800;color:#25F4EE}img{width:330px;height:330px;background:#fff;border-radius:12px;object-fit:contain}
ol{max-width:520px;line-height:1.6;color:#bbb}.st{color:#FE2C55;font-weight:700}.ok{color:#3c3}</style></head><body>
<h1>Iniciar sesión del bot de TikTok</h1><div class="acc" id="acc">…</div><img id="qr" alt="QR">
<div class="st" id="st"></div><div class="ok" id="done"></div>
<ol><li>En la app de TikTok del móvil, cambia a la cuenta de arriba (Perfil → tu nombre arriba → elegir cuenta).</li>
<li>Pulsa el icono de escanear (lupa → icono de escáner, o Perfil → ☰ → Mi código QR → escáner).</li>
<li>Escanea este QR y confirma «Iniciar sesión». La página pasa sola a la siguiente cuenta.</li></ol>
<script>async function t(){try{const s=await (await fetch('/state')).json();
document.getElementById('acc').textContent=s.finished?'¡Listo! Puedes cerrar esta pestaña':(s.handle?'@'+s.handle:'…');
document.getElementById('st').textContent=s.status;document.getElementById('done').textContent=s.done.length?'Conectadas: '+s.done.map(h=>'@'+h).join(', '):'';
if(!s.finished)document.getElementById('qr').src='/qr.png?'+Date.now();else document.getElementById('qr').style.display='none'}catch(e){}}
setInterval(t,2500);t()</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 — silence the default per-request logging
        pass

    def do_GET(self):
        if self.path.startswith("/qr.png"):
            body, ctype = STATE["png"], "image/png"
        elif self.path == "/state":
            body = json.dumps({k: STATE[k] for k in ("handle", "status", "done", "finished")}).encode()
            ctype = "application/json"
        else:
            body, ctype = PAGE.encode(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def qr_shot(page) -> bytes:
    for sel in ("canvas", "img[src^='data:image']", "div[class*='qrcode'] img", "div[class*='QRcode'] img"):
        loc = page.locator(sel).first
        if loc.count() and loc.is_visible():
            box = loc.bounding_box()
            if box and box["width"] > 100:
                return loc.screenshot()
    return page.screenshot()


QR_STATUS = {
    "new": "Escanea el QR con la app (cuenta de arriba)",
    "scanned": "QR escaneado: confirma «Iniciar sesión» en el móvil",
    "confirmed": "Confirmado, guardando la sesión…",
    "expired": "QR caducado, generando uno nuevo…",
}


def login_one(p, account: int, timeout_s: int = 600) -> bool:
    STATE.update(account=account, handle=HANDLES[account], status="Cargando el QR…")
    ctx = _ctx(p, account)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    qr = {"status": None}

    def on_response(r):  # TikTok polls check_qrconnect: new → scanned → confirmed (or expired)
        if "check_qrconnect" in r.url:
            try:
                st = (r.json().get("data") or {}).get("status")
            except Exception:  # noqa: BLE001 — non-JSON poll response
                return
            if st:
                qr["status"] = st
                STATE["status"] = QR_STATUS.get(st, f"Estado del QR: {st}")

    page.on("response", on_response)
    try:
        if _signed_in(page):
            STATE["status"] = "Esta cuenta ya estaba conectada"
            return True
        page.goto(QR_URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(5000)
        start, last_reload = time.time(), time.time()
        while time.time() - start < timeout_s:
            if "/login" not in page.url:
                page.wait_for_timeout(4000)
                ok = _signed_in(page)
                STATE["status"] = "Conectada ✔" if ok else "El login no se completó, vuelve a escanear"
                if ok:
                    return True
                page.goto(QR_URL, wait_until="domcontentloaded", timeout=90_000)
            expired = qr["status"] == "expired" or page.get_by_text("expired", exact=False).count()
            stale = time.time() - last_reload > 110 and qr["status"] not in ("scanned", "confirmed")
            if expired or stale:  # TikTok QR codes expire after ~2 min
                page.goto(QR_URL, wait_until="domcontentloaded", timeout=90_000)
                page.wait_for_timeout(4000)
                last_reload = time.time()
                qr["status"] = None
            STATE["png"] = qr_shot(page)
            if qr["status"] is None:
                STATE["status"] = QR_STATUS["new"]
            page.wait_for_timeout(2000)
        STATE["status"] = "Tiempo agotado para esta cuenta"
        return False
    finally:
        ctx.close()


def main() -> None:
    from playwright.sync_api import sync_playwright

    accounts = [int(a) for a in sys.argv[1:]] or list(HANDLES)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"http://127.0.0.1:{PORT}", flush=True)
    with sync_playwright() as p:
        for a in accounts:
            if login_one(p, a):
                STATE["done"].append(HANDLES[a])
            print(a, HANDLES[a], "OK" if HANDLES[a] in STATE["done"] else "FAILED", flush=True)
    STATE.update(finished=True, status="", handle=None)
    time.sleep(30)  # let the page show the final state
    server.shutdown()


if __name__ == "__main__":
    main()
