"""Upload a finished clip to YouTube Shorts, TikTok and Instagram Reels.

Each platform is skipped (not failed) when its credentials are missing, so the
pipeline works before every account is connected.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _req(url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body = r.read()
            return json.loads(body) if body else {"_headers": dict(r.headers)}
    except urllib.error.HTTPError as e:
        # The API's JSON body says *why* (e.g. TikTok's unaudited_client_can_only_post_to_private_accounts).
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:400].decode(errors='ignore')}") from None


def _form(d: dict) -> bytes:
    return urllib.parse.urlencode(d).encode()


# ---------------- YouTube ----------------
def youtube(path: Path, title: str, description: str) -> str | None:
    cid, secret, refresh = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if not (cid and secret and refresh):
        return None
    tok = _req("https://oauth2.googleapis.com/token", _form({
        "client_id": cid, "client_secret": secret, "refresh_token": refresh, "grant_type": "refresh_token"}))["access_token"]
    meta = {
        "snippet": {"title": title[:95] + " #shorts", "description": description, "categoryId": "20"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    size = path.stat().st_size
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(), method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    with urllib.request.urlopen(req, timeout=60) as r:
        upload_url = r.headers["Location"]
    res = _req(upload_url, path.read_bytes(), {"Content-Type": "video/mp4"}, "PUT")
    return f"https://youtube.com/shorts/{res['id']}"


# ---------------- TikTok ----------------
def _tiktok_token() -> str | None:
    key, secret, refresh = (os.environ.get(k) for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"))
    if not (key and secret and refresh):
        return None
    res = _req("https://open.tiktokapis.com/v2/oauth/token/", _form({
        "client_key": key, "client_secret": secret, "grant_type": "refresh_token", "refresh_token": refresh}),
        {"Content-Type": "application/x-www-form-urlencoded"})
    if res.get("refresh_token") and res["refresh_token"] != refresh:
        Path("tiktok_refresh_token.new").write_text(res["refresh_token"])  # workflow rotates the secret
    return res["access_token"]


def tiktok(path: Path, caption: str) -> str | None:
    tok = _tiktok_token()
    if not tok:
        return None
    auth = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}
    info = _req("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", b"{}", auth)["data"]
    options = info.get("privacy_level_options", ["SELF_ONLY"])
    privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else "SELF_ONLY"
    size = path.stat().st_size
    init = _req("https://open.tiktokapis.com/v2/post/publish/video/init/", json.dumps({
        "post_info": {"title": caption[:2200], "privacy_level": privacy,
                      "disable_comment": False, "disable_duet": False, "disable_stitch": False},
        # Files <= 64 MiB must be sent as one chunk equal to the whole file.
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
    }).encode(), auth)["data"]
    _req(init["upload_url"], path.read_bytes(), {
        "Content-Type": "video/mp4", "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}"}, "PUT")
    return f"tiktok:{init['publish_id']} ({privacy})"


# ---------------- Instagram (Instagram API with Instagram Login) ----------------
def instagram(public_url: str | None, caption: str) -> str | None:
    tok, uid = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if not (tok and uid and public_url):
        return None
    base = "https://graph.instagram.com/v23.0"
    c = _req(f"{base}/{uid}/media", _form({"media_type": "REELS", "video_url": public_url,
                                            "caption": caption, "share_to_feed": "true", "access_token": tok}))
    for _ in range(40):
        st = _req(f"{base}/{c['id']}?fields=status_code&access_token={tok}")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram processing error: {st}")
        time.sleep(15)
    pub = _req(f"{base}/{uid}/media_publish", _form({"creation_id": c["id"], "access_token": tok}))
    return f"instagram:{pub['id']}"


def publish_all(path: Path, title: str, caption: str, public_url: str | None) -> dict:
    results = {}
    for name, fn in (("youtube", lambda: youtube(path, title, caption)),
                     ("tiktok", lambda: tiktok(path, caption)),
                     ("instagram", lambda: instagram(public_url, caption))):
        try:
            results[name] = fn() or "skipped (no credentials)"
        except Exception as e:  # one platform failing must not block the others
            results[name] = f"error: {e}"
        print(f"  {name}: {results[name]}")
    return results
