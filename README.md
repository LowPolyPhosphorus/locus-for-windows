# Locus for Windows

Locus blocks distracting apps and websites while you work or study. It can pull upcoming assignments straight from Notion or any calendar (Google Calendar, Outlook, Schoology, Canvas, etc.) so starting a session is just one click.

If something gets blocked that you actually need, it asks why. The AI reads your reason and decides whether to let it through. No reason, no access.

> Windows port of the original [Locus](https://github.com/K-man1/locus) by [K-man1](https://github.com/K-man1), who built the macOS app, the website, and all the original code. This repo adapts it for Windows.

Website: **https://locusfocusapp.netlify.app**

---

## Install

### Option A: Installer (not available yet - no releases)
1. Download **LocusSetup.exe** from the [Releases page](../../releases/latest).
2. Run it, click through the prompts.
3. Look for the Locus icon in your system tray (bottom-right corner, might be hiding under `^`).

### Option B: Run from source
You need Python 3.11+ and Google Chrome.

```powershell
git clone https://github.com/LowPolyPhosphorus/locus-for-windows
cd locus-for-windows
pip install -r requirements.txt
mkdir "$env:APPDATA\Locus" -Force
copy config.example.json "$env:APPDATA\Locus\config.json"
.\run.ps1
```

---

## Setup

Before your first session, open `%APPDATA%\Locus\config.json` in any text editor and at minimum change two things:

- **`override_code`** -- set this to something only you know. It's your emergency bypass if the AI blocks something it shouldn't.
- **`ical_feeds`** or **Notion credentials** -- paste in your calendar URL or Notion API key if you want assignments to show up automatically. Totally optional, you can always just type a session name manually.

The app reloads config automatically so no restart needed.

---

## Using it

Right-click the tray icon to get started.

Hit **Start Session...** and either pick an assignment from the list or type whatever you're working on. Locus starts blocking everything that isn't on the whitelist. If you try to open something blocked, a popup appears asking for a reason -- type one and the AI decides. Good reason? Allowed for 15 minutes. Bad reason? Stays blocked.

Hit **End Session** when you're done. Temporary allowances reset so next session starts clean.

### Chrome and website blocking

Locus hooks into Chrome via the DevTools Protocol. `run.ps1` launches Chrome with the right flags automatically. If you open Chrome yourself, you need to add:

```
chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
```

Otherwise website blocking won't work.

### Adding apps that should never get blocked

By default things like Explorer, Terminal, Task Manager and Chrome are always allowed. To add your own (say, Vivaldi or the Claude desktop app), edit your config:

```json
"always_allowed_apps": ["Vivaldi", "Claude"],
"always_allowed_domains": ["claude.ai", "notion.so"]
```

---

## Config reference

| Key | Default | What it does |
|---|---|---|
| `override_code` | `"CHANGEME"` | Emergency bypass password |
| `temporary_allow_minutes` | `15` | How long an approved app/site stays allowed |
| `app_poll_interval_seconds` | `15` | How often it checks for blocked apps |
| `url_poll_interval_seconds` | `1` | How often it checks your browser tab |
| `always_allowed_apps` | `[]` | Apps that are never blocked, ever |
| `always_allowed_domains` | `[]` | Domains that are never blocked, ever |
| `notion_enabled` | `false` | Turn on Notion integration |
| `harshness` | `"Standard"` | How strict the AI is: Lenient, Standard, or Strict |

---

## Building

```powershell
pip install pyinstaller
.\build_daemon.ps1
```

This spits out `dist\Locus.exe` and `dist\locusd.exe`. To package it into an installer, grab [Inno Setup](https://jrsoftware.org/isinfo.php) and run:

```
ISCC.exe package_installer.iss
```

---

## License
MIT -- see [LICENSE](LICENSE).
