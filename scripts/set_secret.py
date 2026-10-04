"""Set a GitHub Actions secret. Value is read from env SECRET_VALUE, never printed."""
import base64, json, os, sys, urllib.request
from nacl import encoding, public

repo, name = sys.argv[1], sys.argv[2]
tok = os.environ["GH_TOK"]
h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
with urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=h)) as r:
    key = json.load(r)
box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder))
enc = base64.b64encode(box.encrypt(os.environ["SECRET_VALUE"].encode())).decode()
req = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/secrets/{name}", method="PUT",
                             data=json.dumps({"encrypted_value": enc, "key_id": key["key_id"]}).encode(), headers=h)
with urllib.request.urlopen(req) as r:
    print(name, r.status)
