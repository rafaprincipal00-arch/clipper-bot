"""Get a YouTube refresh token for one channel with a Desktop OAuth client (loopback redirect, no Vercel).

    python scripts/yt_oauth.py <client.json> <out.json> [port]

client.json = {"client_id", "client_secret"} (kept outside the repo). Prints the consent URL, waits for Google
to redirect to http://127.0.0.1:<port>/, exchanges the code and writes {"refresh_token", "channel"} to out.json.
Each Google Cloud project has its own 10,000-unit/day upload quota, so one project per channel = 6 uploads/day
per channel instead of 6/day shared.
"""
import json
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def main() -> None:
    client = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2]
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 8790
    redirect = f"http://127.0.0.1:{port}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent select_account"})
    print(url, flush=True)
    got: dict = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Listo, ya puedes cerrar esta ventana.</h2>".encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), H)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    if "error" in got:
        sys.exit(f"error: {got['error']}")
    tok = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "client_id": client["client_id"], "client_secret": client["client_secret"], "code": got["code"],
        "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()))
    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                                 headers={"Authorization": f"Bearer {tok['access_token']}"})
    items = json.load(urllib.request.urlopen(req)).get("items", [])
    ch = [f"{i['snippet']['title']} {i['snippet'].get('customUrl', '')}" for i in items]
    json.dump({"refresh_token": tok.get("refresh_token"), "channel": ch}, open(out, "w", encoding="utf-8"))
    print("OK channel:", ch, "refresh_token:", bool(tok.get("refresh_token")), flush=True)


if __name__ == "__main__":
    main()
