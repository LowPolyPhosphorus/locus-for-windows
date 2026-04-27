# Deploying the Locus AI Proxy to Cloudflare Workers

You only need to do this **once**. After deploy, Locus clients will route all AI
calls through your Worker, which keeps the Hack Club key out of the shipped binary.

---

## Step 1 — Create a free Cloudflare account

1. Go to <https://dash.cloudflare.com/sign-up>
2. Sign up with your email. Verify the email.
3. When it asks you to add a site, skip it ("I'll do it later" / close the page). We don't need a domain — Workers get a free `workers.dev` subdomain.

---

## Step 2 — Install Wrangler (the Cloudflare CLI)

Open Terminal and run:

```bash
npm install -g wrangler
```

If you get "command not found: npm", install Node first:

```bash
brew install node
```

Verify it works:

```bash
wrangler --version
```

You should see something like `wrangler 3.x.x`.

---

## Step 3 — Log in

```bash
wrangler login
```

This opens your browser. Click **Allow**. Come back to the terminal — it will say `Successfully logged in`.

---

## Step 4 — Deploy the Worker

From the Locus repo root:

```bash
cd /Users/User/Desktop/focus/cloudflare_worker
wrangler deploy
```

On the **first** deploy it asks you to pick a `workers.dev` subdomain. Pick anything (e.g. `kc-locus`). You only pick once; it becomes part of your URL forever.

When it finishes it prints a URL like:

```
https://locus-proxy.kc-locus.workers.dev
```

**Copy that URL — you need it in Step 6.**

---

## Step 5 — Add the Hack Club key as a secret

```bash
wrangler secret put HACKCLUB_KEY
```

When prompted, paste this and press Enter:

```
sk-hc-v1-1e6f6bf403ff4cfabb8f74227451e60a72300161432e4890bd54950ae3e557bf
```

Nothing will echo back — that's normal (it's a secret).

---

## Step 5b — Set up Notion OAuth (for "Sign in with Notion")

If you want users to sign in with their Notion account instead of pasting an
integration token, do these one-time steps. (Skip if you only want the AI proxy.)

### 5b.1 — Create a public Notion integration

1. Go to <https://www.notion.so/profile/integrations> → **New integration**
2. Type: **Public**
3. Capabilities: read user, read content, read comments (whatever your DB needs)
4. Redirect URIs — add **exactly** the worker URL from Step 4 with `/oauth/notion`
   appended. For example:
   ```
   https://locus-proxy.kc-locus.workers.dev/oauth/notion
   ```
5. Save. You now have a **Client ID** and a **Client secret**.

### 5b.2 — Update the worker's redirect URI

Open `cloudflare_worker/worker.js` and change `NOTION_REDIRECT_URI` to match
the URL you registered in 5b.1:

```js
const NOTION_REDIRECT_URI = "https://locus-proxy.kc-locus.workers.dev/oauth/notion";
```

### 5b.3 — Add the Notion secrets to the worker

```bash
wrangler secret put NOTION_CLIENT_ID         # paste the OAuth client ID
wrangler secret put NOTION_CLIENT_SECRET     # paste the OAuth client secret
wrangler deploy                              # redeploy with the new redirect URI
```

### 5b.4 — Tell the macOS app the public client ID + redirect URI

Open `FocusLockApp/FocusLockApp/NotionOAuth.swift` and update the two
constants:

```swift
static let clientID    = "YOUR_NOTION_CLIENT_ID"   // ← paste OAuth client ID
static let redirectURI = "https://locus-proxy.kc-locus.workers.dev/oauth/notion"
//                       ^^^ must exactly match the URL registered in 5b.1
```

The client ID is **not** a secret — it appears in the authorize URL. The
client secret stays on the worker only.

After this, rebuild (Step 8) and the Connectors → Notion tab will show a
"Sign in with Notion" button instead of an API-key field.

---

## Step 5c — Set up Google Calendar OAuth (for "Sign in with Google")

Skip if you don't want calendar integration.

### 5c.1 — Create a Google Cloud OAuth client

1. Go to <https://console.cloud.google.com/> and create (or pick) a project.
2. Enable the **Google Calendar API**: APIs & Services → Library → search
   "Google Calendar API" → Enable.
3. APIs & Services → OAuth consent screen → choose **External**, fill in
   the basics. Add test users (your own Google account) while it's in
   "Testing" mode — that's all you need for personal use.
4. APIs & Services → Credentials → **Create Credentials → OAuth client ID**:
   - Type: **Web application**
   - Authorized redirect URIs: add **exactly** the worker URL with
     `/oauth/google` appended, e.g.
     ```
     https://locus-proxy.kc-locus.workers.dev/oauth/google
     ```
5. Save — you now have a **Client ID** and a **Client secret**.

### 5c.2 — Update the worker's redirect URI

If your worker subdomain isn't `locus-proxy`, edit
`cloudflare_worker/worker.js` and change `GOOGLE_REDIRECT_URI` to match the
URL you registered above.

### 5c.3 — Add the Google secrets to the worker

```bash
wrangler secret put GOOGLE_CLIENT_ID         # paste OAuth client ID
wrangler secret put GOOGLE_CLIENT_SECRET     # paste OAuth client secret
wrangler deploy                              # redeploy with the new endpoints
```

### 5c.4 — Tell the macOS app the public client ID

Open `FocusLockApp/FocusLockApp/GoogleOAuth.swift` and update:

```swift
static let clientID    = "YOUR_GOOGLE_CLIENT_ID"   // ← paste OAuth client ID
static let redirectURI = "https://locus-proxy.kc-locus.workers.dev/oauth/google"
//                       ^^^ must exactly match the URI registered in 5c.1
```

Rebuild (Step 8). Connectors → Google Calendar will show a "Sign in with
Google" button and a multi-select calendar picker.

---

## Step 6 — Point the Locus client at your Worker

Open `focuslock/claude_client.py` and change the `PROXY_URL` line. Replace `PLACEHOLDER` with your subdomain from Step 4:

```python
# Before
PROXY_URL = "https://locus-proxy.PLACEHOLDER.workers.dev/"

# After (example)
PROXY_URL = "https://locus-proxy.kc-locus.workers.dev/"
```

Save the file.

---

## Step 7 — Test it

```bash
curl -X POST https://locus-proxy.YOUR-SUBDOMAIN.workers.dev/ \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Say hello in 5 words","device_id":"test-device"}'
```

You should see `{"text":"Hello there, my friend!"}` or similar.

---

## Step 8 — Rebuild the daemon binary

From the Locus repo root:

```bash
./build_daemon.sh        # rebuild locusd with the new URL baked in
cd FocusLockApp
./build.sh               # rebuild Locus.app with the new daemon
```

Launch `FocusLockApp/build/Locus.app`. Try to visit a blocked site during a
session — the AI eval should work. Check the Cloudflare dashboard → Workers →
`locus-proxy` → you'll see request counts tick up.

---

## Notes

- **Free tier**: 100,000 requests/day. You won't come close.
- **Changing the upstream model later**: edit `cloudflare_worker/worker.js`, rerun `wrangler deploy`. No client update needed.
- **Rate limiting**: the Worker caps each device ID at 120 requests/hour. If you hit it during testing, wait an hour or change the limit in `worker.js`.
- **Revoking access**: if someone extracts a device ID from a binary, you can blocklist it by adding a check in `worker.js` and redeploying.
