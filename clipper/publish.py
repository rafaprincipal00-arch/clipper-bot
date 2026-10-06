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
import zlib
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
def _pick(tokens: list[str], name: str, account: int | None) -> str:
    """Account `account` (0-based) when the run assigns one clip per account; otherwise turns by clip name."""
    return tokens[account % len(tokens)] if account is not None else tokens[zlib.crc32(name.encode()) % len(tokens)]


def youtube(path: Path, title: str, description: str, account: int | None = None) -> str | None:
    """Channels (YT_REFRESH_TOKEN, _2, _3...) take turns by clip name, like the TikTok accounts.
    The upload quota belongs to the Google Cloud project, so it is shared by every channel."""
    cid, secret = os.environ.get("YT_CLIENT_ID"), os.environ.get("YT_CLIENT_SECRET")
    keys = ["YT_REFRESH_TOKEN"] + [f"YT_REFRESH_TOKEN_{i}" for i in range(2, 6)]
    tokens = [os.environ[k] for k in keys if os.environ.get(k)]
    if not (cid and secret and tokens):
        return None
    refresh = _pick(tokens, path.stem, account)
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
def _tiktok_refresh_tokens() -> list[str]:
    """TIKTOK_REFRESH_TOKEN, TIKTOK_REFRESH_TOKEN_2, _3... one per connected TikTok account."""
    keys = ["TIKTOK_REFRESH_TOKEN"] + [f"TIKTOK_REFRESH_TOKEN_{i}" for i in range(2, 6)]
    return [os.environ[k] for k in keys if os.environ.get(k)]


def _tiktok_token(name: str = "", account: int | None = None) -> str | None:
    """Access token for the account that gets this clip: accounts take turns by clip name, so each
    account posts different clips (identical uploads across accounts get flagged as duplicates)."""
    key, secret = os.environ.get("TIKTOK_CLIENT_KEY"), os.environ.get("TIKTOK_CLIENT_SECRET")
    tokens = _tiktok_refresh_tokens()
    if not (key and secret and tokens):
        return None
    refresh = _pick(tokens, name, account)
    res = _req("https://open.tiktokapis.com/v2/oauth/token/", _form({
        "client_key": key, "client_secret": secret, "grant_type": "refresh_token", "refresh_token": refresh}),
        {"Content-Type": "application/x-www-form-urlencoded"})
    if res.get("refresh_token") and res["refresh_token"] != refresh:
        Path("tiktok_refresh_token.new").write_text(res["refresh_token"])  # workflow rotates the secret
    return res["access_token"]


def tiktok(path: Path, caption: str, account: int | None = None) -> str | None:
    tok = _tiktok_token(path.name, account)
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


def tiktok_draft(path: Path, account: int | None = None) -> str | None:
    """Upload to the creator's TikTok inbox as a draft (video.upload scope, works without the app audit).
    The creator gets a notification, adds a trending sound from TikTok's licensed library and posts it
    publicly from the app."""
    tok = _tiktok_token(path.name, account)
    if not tok:
        return None
    auth = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}
    size = path.stat().st_size
    init = _req("https://open.tiktokapis.com/v2/post/publish/inbox/video/init/", json.dumps({
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
    }).encode(), auth)["data"]
    _req(init["upload_url"], path.read_bytes(), {
        "Content-Type": "video/mp4", "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}"}, "PUT")
    return f"tiktok-draft:{init['publish_id']}"


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


def publish_all(path: Path, title: str, caption: str, public_url: str | None, skip: set[str] | None = None,
                account: int | None = None) -> dict:
    """account: 0-based index of the YouTube channel + TikTok account that get this clip (None = by clip name)."""
    results = {}
    for name, fn in (("youtube", lambda: youtube(path, title, caption, account)),
                     ("tiktok", lambda: tiktok_draft(path, account) if os.environ.get("TIKTOK_MODE", "draft") == "draft"
                      else tiktok(path, caption, account)),
                     ("instagram", lambda: instagram(public_url, caption))):
        if skip and name in skip:
            results[name] = "skipped (daily cap)"
            continue
        try:
            results[name] = fn() or "skipped (no credentials)"
        except Exception as e:  # one platform failing must not block the others
            results[name] = f"error: {e}"
        print(f"  {name}: {results[name]}")
    return results
