// Locus AI proxy + OAuth relay.
//   POST /                       → forward AI eval prompt to Hack Club
//   GET  /oauth/notion            → Notion OAuth callback
//   GET  /oauth/google            → Google OAuth callback
//   POST /oauth/google/refresh    → swap refresh_token → fresh access_token
// Secrets held on the Worker (never shipped): HACKCLUB_KEY, NOTION_CLIENT_ID,
// NOTION_CLIENT_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET.

const HACKCLUB_URL = "https://ai.hackclub.com/proxy/v1/chat/completions";
const MODEL = "google/gemini-2.5-flash-lite-preview-09-2025";
const NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token";
const NOTION_REDIRECT_URI = "https://locus-proxy.locus-proxy.workers.dev/oauth/notion";
const NOTION_APP_SCHEME = "locus://oauth/notion";

const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GOOGLE_REDIRECT_URI = "https://locus-proxy.locus-proxy.workers.dev/oauth/google";
const GOOGLE_APP_SCHEME = "locus://oauth/google";

// Rough per-device rate limit (best-effort; Workers are stateless so we use
// the Cache API as a 1-hour counter). Not cryptographic — just a speed bump.
const LIMIT_PER_HOUR = 120;

async function rateLimitOK(deviceId, cache) {
    const key = new Request(`https://rl.locus/${deviceId}`);
    const hit = await cache.match(key);
    let count = hit ? parseInt(await hit.text(), 10) || 0 : 0;
    if (count >= LIMIT_PER_HOUR) return false;
    count += 1;
    await cache.put(
        key,
        new Response(String(count), {
            headers: { "Cache-Control": "max-age=3600" },
        })
    );
    return true;
}

async function handleNotionOAuth(request, env) {
    const url = new URL(request.url);
    const code = url.searchParams.get("code");
    const error = url.searchParams.get("error");
    if (error) return bounceBack(NOTION_APP_SCHEME, { error });
    if (!code) return new Response("missing code", { status: 400 });

    const basic = btoa(`${env.NOTION_CLIENT_ID}:${env.NOTION_CLIENT_SECRET}`);
    const resp = await fetch(NOTION_TOKEN_URL, {
        method: "POST",
        headers: {
            Authorization: `Basic ${basic}`,
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            grant_type: "authorization_code",
            code,
            redirect_uri: NOTION_REDIRECT_URI,
        }),
    });
    if (!resp.ok) {
        const txt = await resp.text();
        return bounceBack(NOTION_APP_SCHEME, { error: `exchange_failed_${resp.status}`, detail: txt.slice(0, 200) });
    }
    const data = await resp.json();
    return bounceBack(NOTION_APP_SCHEME, {
        token: data.access_token || "",
        workspace: data.workspace_name || "",
        workspace_id: data.workspace_id || "",
    });
}

async function handleGoogleOAuth(request, env) {
    const url = new URL(request.url);
    const code = url.searchParams.get("code");
    const error = url.searchParams.get("error");
    if (error) return bounceBack(GOOGLE_APP_SCHEME, { error });
    if (!code) return new Response("missing code", { status: 400 });

    const params = new URLSearchParams({
        code,
        client_id: env.GOOGLE_CLIENT_ID,
        client_secret: env.GOOGLE_CLIENT_SECRET,
        redirect_uri: GOOGLE_REDIRECT_URI,
        grant_type: "authorization_code",
    });
    const resp = await fetch(GOOGLE_TOKEN_URL, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: params.toString(),
    });
    if (!resp.ok) {
        const txt = await resp.text();
        return bounceBack(GOOGLE_APP_SCHEME, { error: `exchange_failed_${resp.status}`, detail: txt.slice(0, 200) });
    }
    const data = await resp.json();
    return bounceBack(GOOGLE_APP_SCHEME, {
        access_token: data.access_token || "",
        refresh_token: data.refresh_token || "",
        expires_in: String(data.expires_in || 0),
    });
}

async function handleGoogleRefresh(request, env) {
    let body;
    try { body = await request.json(); } catch { return new Response("bad json", { status: 400 }); }
    const refreshToken = (body.refresh_token || "").toString();
    if (!refreshToken) return new Response("refresh_token required", { status: 400 });

    const params = new URLSearchParams({
        client_id: env.GOOGLE_CLIENT_ID,
        client_secret: env.GOOGLE_CLIENT_SECRET,
        refresh_token: refreshToken,
        grant_type: "refresh_token",
    });
    const resp = await fetch(GOOGLE_TOKEN_URL, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: params.toString(),
    });
    if (!resp.ok) {
        return new Response(JSON.stringify({ error: "refresh_failed", status: resp.status }), {
            status: 502, headers: { "Content-Type": "application/json" },
        });
    }
    const data = await resp.json();
    return new Response(JSON.stringify({
        access_token: data.access_token || "",
        expires_in: data.expires_in || 0,
    }), { headers: { "Content-Type": "application/json" } });
}

function bounceBack(scheme, params) {
    // OAuth provider redirects the browser here → we bounce to the custom
    // URL scheme, which macOS routes to Locus.app. The HTML fallback covers
    // browsers that block automatic scheme redirects.
    const qs = new URLSearchParams(params).toString();
    const target = `${scheme}?${qs}`;
    const safeTarget = target.replace(/"/g, "&quot;");
    const html = `<!doctype html>
<html><head><meta charset="utf-8"><title>Locus — Signing you in…</title>
<meta http-equiv="refresh" content="0; url=${safeTarget}">
<style>body{font-family:-apple-system,system-ui;padding:60px;text-align:center;color:#333}
a{color:#0366d6}</style></head>
<body>
<h2>Signing you in to Locus…</h2>
<p>If this page doesn't close automatically, <a href="${safeTarget}">click here to return to Locus</a>.</p>
<script>window.location.replace(${JSON.stringify(target)})</script>
</body></html>`;
    return new Response(html, {
        status: 200,
        headers: { "Content-Type": "text/html; charset=utf-8" },
    });
}

export default {
    async fetch(request, env) {
        const url = new URL(request.url);
        if (url.pathname === "/oauth/notion" && request.method === "GET") {
            return handleNotionOAuth(request, env);
        }
        if (url.pathname === "/oauth/google" && request.method === "GET") {
            return handleGoogleOAuth(request, env);
        }
        if (url.pathname === "/oauth/google/refresh" && request.method === "POST") {
            return handleGoogleRefresh(request, env);
        }
        if (request.method !== "POST") {
            return new Response("POST only", { status: 405 });
        }
        let body;
        try {
            body = await request.json();
        } catch {
            return new Response("bad json", { status: 400 });
        }
        const prompt = (body.prompt || "").toString();
        const deviceId = (body.device_id || "").toString().slice(0, 128);
        if (!prompt || !deviceId) {
            return new Response("prompt and device_id required", { status: 400 });
        }

        const cache = caches.default;
        if (!(await rateLimitOK(deviceId, cache))) {
            return new Response(JSON.stringify({ error: "rate_limited" }), {
                status: 429,
                headers: { "Content-Type": "application/json" },
            });
        }

        const upstream = await fetch(HACKCLUB_URL, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${env.HACKCLUB_KEY}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                model: MODEL,
                messages: [{ role: "user", content: prompt }],
                max_tokens: 200,
            }),
        });

        if (!upstream.ok) {
            return new Response(
                JSON.stringify({ error: "upstream", status: upstream.status }),
                { status: 502, headers: { "Content-Type": "application/json" } }
            );
        }

        const data = await upstream.json();
        const text = data?.choices?.[0]?.message?.content?.trim() || "";
        return new Response(JSON.stringify({ text }), {
            headers: { "Content-Type": "application/json" },
        });
    },
};
