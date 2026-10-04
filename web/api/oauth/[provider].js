// OAuth start + callback for YouTube, TikTok and Instagram.
// GET /api/oauth/<provider>          -> redirect to the provider's consent screen
// GET /api/oauth/<provider>?code=... -> exchange code, show the token to store as a GitHub secret

const PROVIDERS = {
  youtube: {
    id: "YT_CLIENT_ID",
    secret: "YT_CLIENT_SECRET",
    authorize: (cid, redirect, state) =>
      "https://accounts.google.com/o/oauth2/v2/auth?" +
      new URLSearchParams({
        client_id: cid, redirect_uri: redirect, response_type: "code", state,
        scope: "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
        access_type: "offline", prompt: "consent",
      }),
    exchange: (cid, secret, redirect, code) =>
      post("https://oauth2.googleapis.com/token", {
        client_id: cid, client_secret: secret, redirect_uri: redirect, code, grant_type: "authorization_code",
      }),
    secrets: (t) => ({ YT_REFRESH_TOKEN: t.refresh_token }),
  },
  tiktok: {
    id: "TIKTOK_CLIENT_KEY",
    secret: "TIKTOK_CLIENT_SECRET",
    authorize: (cid, redirect, state) =>
      "https://www.tiktok.com/v2/auth/authorize/?" +
      new URLSearchParams({
        client_key: cid, redirect_uri: redirect, response_type: "code", state,
        scope: "user.info.basic,video.publish,video.upload",
      }),
    exchange: (cid, secret, redirect, code) =>
      post("https://open.tiktokapis.com/v2/oauth/token/", {
        client_key: cid, client_secret: secret, redirect_uri: redirect, code, grant_type: "authorization_code",
      }),
    secrets: (t) => ({ TIKTOK_REFRESH_TOKEN: t.refresh_token }),
  },
  instagram: {
    id: "IG_APP_ID",
    secret: "IG_APP_SECRET",
    authorize: (cid, redirect, state) =>
      "https://www.instagram.com/oauth/authorize?" +
      new URLSearchParams({
        client_id: cid, redirect_uri: redirect, response_type: "code", state,
        scope: "instagram_business_basic,instagram_business_content_publish",
      }),
    exchange: async (cid, secret, redirect, code) => {
      const short = await post("https://api.instagram.com/oauth/access_token", {
        client_id: cid, client_secret: secret, redirect_uri: redirect, code, grant_type: "authorization_code",
      });
      if (!short.access_token) return short;
      // Swap the 1 h token for a 60-day one.
      const r = await fetch(
        "https://graph.instagram.com/access_token?" +
          new URLSearchParams({ grant_type: "ig_exchange_token", client_secret: secret, access_token: short.access_token }),
      );
      const long = await r.json();
      return { ...long, user_id: short.user_id };
    },
    secrets: (t) => ({ IG_ACCESS_TOKEN: t.access_token, IG_USER_ID: String(t.user_id) }),
  },
};

async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body),
  });
  return r.json();
}

const page = (title, body) => `<!doctype html><meta charset="utf-8"><title>${title}</title>
<body style="max-width:760px;margin:40px auto;padding:0 20px;font:15px/1.6 system-ui;background:#0d0f12;color:#e8ebef">
<h1>${title}</h1>${body}<p><a style="color:#4ade80" href="/connect.html">Volver</a></p></body>`;

const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export default async function handler(req, res) {
  const name = req.query.provider;
  const p = PROVIDERS[name];
  if (!p) return res.status(404).send("unknown provider");
  const cid = process.env[p.id];
  const secret = process.env[p.secret];
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  if (!cid || !secret) {
    return res.status(500).send(page("Falta configuración", `<p>Añade <code>${p.id}</code> y <code>${p.secret}</code> en las variables de entorno de Vercel.</p>`));
  }
  const redirect = `https://${req.headers.host}/api/oauth/${name}`;
  const { code, state, error } = req.query;
  if (error) return res.status(400).send(page("Cancelado", `<p>${escapeHtml(error)}</p>`));
  if (!code) {
    const st = crypto.randomUUID();
    res.setHeader("Set-Cookie", `oauth_state=${st}; Path=/api/oauth; HttpOnly; Secure; SameSite=Lax; Max-Age=600`);
    res.writeHead(302, { Location: p.authorize(cid, redirect, st) });
    return res.end();
  }
  const cookieState = /oauth_state=([\w-]+)/.exec(req.headers.cookie || "")?.[1];
  if (!cookieState || cookieState !== state) return res.status(400).send(page("Estado inválido", "<p>Vuelve a empezar.</p>"));
  const tokens = await p.exchange(cid, secret, redirect, code);
  const values = p.secrets(tokens);
  if (Object.values(values).some((v) => !v || v === "undefined")) {
    return res.status(400).send(page("Error del proveedor", `<pre>${escapeHtml(JSON.stringify(tokens, null, 1))}</pre>`));
  }
  const cmds = Object.entries(values)
    .map(([k, v]) => `gh secret set ${k} -R rafaprincipal00-arch/clipper-bot --body "${escapeHtml(v)}"`)
    .join("\n");
  return res.send(page(`${name} conectado`, `<p>Guarda esto como secret del repo (o pégaselo a Hermes):</p>
<pre style="white-space:pre-wrap;word-break:break-all;background:#161a20;padding:12px">${cmds}</pre>
<p>No lo compartas: da permiso para publicar en la cuenta.</p>`));
}
