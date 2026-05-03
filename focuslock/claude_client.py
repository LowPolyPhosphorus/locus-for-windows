"""AI evaluator -- calls the Locus Cloudflare Worker, which forwards to Hack Club AI.

The real upstream key is held as a Worker secret, not shipped in this binary.
"""

import json
import os
import uuid
import requests

from .paths import CONFIG_PATH, APP_SUPPORT_DIR

PROXY_URL = "https://locus-proxy.locus-proxy.workers.dev/"
DEVICE_ID_PATH = os.path.join(APP_SUPPORT_DIR, "device_id")


def _device_id() -> str:
    try:
        if os.path.exists(DEVICE_ID_PATH):
            with open(DEVICE_ID_PATH) as f:
                v = f.read().strip()
                if v:
                    return v
        v = uuid.uuid4().hex
        os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
        with open(DEVICE_ID_PATH, "w") as f:
            f.write(v)
        return v
    except Exception:
        return "anonymous"


DEFAULT_EVALUATE_REASON = """You are a fair focus session enforcer for a high school student.

Session: **{session_name}**
Blocked {subject_type}: **{subject}**
Student's reason: "{reason}"

Important context:
- "Focus session" does NOT always mean homework. It can mean a coding project, hackathon, game dev, creative work, or any personal project.
- If the session name suggests a dev/tech/creative project (e.g. contains words like "hack", "project", "game", "build", "code", "app", "dev"), be MORE lenient about technical tools -- Steam (for testing games), Unity, VS Code, terminals, browsers, etc. are likely legitimate.
- If the session name suggests academic work (e.g. "math homework", "essay", "study"), be stricter about unrelated apps.
- Give the student the benefit of the doubt. Only deny if the reason is clearly unrelated or obviously an excuse.
- Be more strict for entertainment apps with no plausible work use (Netflix, TikTok, etc.).

Respond in exactly this format:
DECISION: APPROVED or DENIED
REASON: One sentence."""

DEFAULT_EVALUATE_SITE_RELEVANCE = """You are a focus session enforcer for a high school student.

Session: **{session_name}**
Website visited: **{domain}**{title_hint}{site_context}

Use your knowledge of what this website actually is and does. If you know the site, factor that into your decision. If you don't recognize it, use the page context provided above.

Should this site be AUTO-ALLOWED without interrupting the student, or should we ASK them to justify it?

AUTO-ALLOW when the site is clearly a legitimate tool for this session -- for example:
- Reference/research tools directly related to the subject (calculators, dictionaries, documentation)
- Search engines when the page title suggests they're searching for something relevant
- Schoology, Canvas, or any LMS
- Stack Overflow, MDN, or coding docs during a coding session
- Khan Academy, SpanishDict, or similar educational tools during a matching session
- Any site that is obviously a tool, not entertainment

ASK when there is any real doubt -- for example:
- YouTube (even if it could be a tutorial -- ask first)
- Social media of any kind (Reddit, Twitter/X, Discord, TikTok, Instagram)
- Streaming (Netflix, Twitch, Spotify with video)
- Gaming sites or Steam store pages
- Shopping
- News sites unrelated to the session topic
- Any site you don't recognize and the page context doesn't make relevant

When in doubt, ASK. It takes the student 10 seconds to justify it.

Respond in exactly this format:
DECISION: AUTO_ALLOW or ASK
REASON: One sentence explaining what the site is and why."""

DEFAULT_EVALUATE_TITLE = """A student is in a focus session: **{session_name}**

They are on {domain} and the current page title is: "{tab_title}"

Is this clearly relevant to their study session, or is it off-topic?

Examples of OFF-TOPIC:
- Approved Claude to study for a test, but the page title shows they're working on a coding project
- Approved YouTube for a math tutorial, but the title is about Minecraft
- Approved Google for research, but they're reading celebrity news

Be lenient for search pages, homepages, and ambiguous titles.
Be strict when the title clearly contradicts the session subject.
Be understanding of mistakes such as typos or misclicks.
If the user says they got sidetracked, but will refocus, allow it.

Respond in exactly this format:
DECISION: RELEVANT or OFF-TOPIC
REASON: One sentence."""


def _scrape_site_context(domain: str) -> str:
    """Fetch the site's title and meta description to give the AI more context.

    Returns a short string like:
        Page title: "Desmos | Graphing Calculator"
        Description: "A beautiful, free online graphing calculator..."
    Or an empty string if the scrape fails or times out.
    """
    try:
        url = f"https://{domain}"
        resp = requests.get(url, timeout=4, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Locus/1.0)",
        }, allow_redirects=True)
        html = resp.text[:8000]  # only read the head section

        # Pull <title>
        title = ""
        t_start = html.lower().find("<title>")
        t_end = html.lower().find("</title>")
        if t_start != -1 and t_end != -1:
            title = html[t_start + 7:t_end].strip()[:120]

        # Pull meta description
        desc = ""
        import re
        m = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            html, re.IGNORECASE
        )
        if not m:
            m = re.search(
                r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
                html, re.IGNORECASE
            )
        if m:
            desc = m.group(1).strip()[:200]

        parts = []
        if title:
            parts.append(f'Page title: "{title}"')
        if desc:
            parts.append(f'Description: "{desc}"')
        return "\n" + "\n".join(parts) if parts else ""

    except Exception:
        return ""


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


class ClaudeClient:
    def _get_prompt(self, key: str, default: str) -> str:
        cfg = _load_config()
        prompts = cfg.get("prompts", {})
        val = prompts.get(key, "").strip()
        return val if val else default

    def _post(self, prompt: str) -> tuple[bool, str, str]:
        """Returns (ok, raw_text, error_str)."""
        payload = {"prompt": prompt, "device_id": _device_id()}
        try:
            resp = requests.post(PROXY_URL, json=payload, timeout=15)
            if resp.status_code == 429:
                return False, "", "rate limited -- try again in a bit"
            resp.raise_for_status()
            return True, (resp.json().get("text") or "").strip(), ""
        except Exception as e:
            return False, "", str(e)

    def evaluate_reason(
        self,
        subject: str,
        subject_type: str,
        session_name: str,
        reason: str,
    ) -> tuple[bool, str]:
        """Returns (approved: bool, explanation: str)."""
        template = self._get_prompt("evaluate_reason", DEFAULT_EVALUATE_REASON)
        prompt = template.format(
            subject=subject,
            subject_type=subject_type,
            session_name=session_name,
            reason=reason,
        )

        ok, text, err = self._post(prompt)
        print(f"[Locus] evaluate_reason response ok={ok} text={text[:100]}")
        if not ok:
            return False, f"AI evaluator unreachable: {err}"

        approved = False
        explanation = "No explanation."
        for line in text.split("\n"):
            upper = line.upper().strip()
            if upper.startswith("DECISION:"):
                verdict = upper.replace("DECISION:", "").strip()
                approved = verdict == "APPROVED"
            elif line.upper().startswith("REASON:"):
                explanation = line.split(":", 1)[1].strip() if ":" in line else line.strip()
        return approved, explanation

    def evaluate_title(self, tab_title: str, session_name: str, domain: str = "") -> tuple[bool, str]:
        """Check if a page title is on-topic for the current session."""
        template = self._get_prompt("evaluate_title", DEFAULT_EVALUATE_TITLE)
        prompt = template.format(
            session_name=session_name,
            domain=domain or "a website",
            tab_title=tab_title,
        )

        ok, text, _ = self._post(prompt)
        if not ok:
            return True, ""  # Fail open

        relevant = True
        reason = "No explanation."
        for line in text.split("\n"):
            upper = line.upper().strip()
            if upper.startswith("DECISION:"):
                verdict = upper.replace("DECISION:", "").strip()
                relevant = verdict == "RELEVANT"
            elif line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip() if ":" in line else line.strip()
        return relevant, reason

    def evaluate_site_relevance(
        self,
        domain: str,
        session_name: str,
        tab_title: str = "",
    ) -> tuple[bool, str]:
        """Pre-screen: is this site obviously relevant to the session?

        Scrapes the site's meta description for context, then asks the AI
        using both its own knowledge of the site and the scraped context.
        Only interrupts the user if there's genuine doubt.
        """
        # Scrape the site for context -- runs in ~1-4 seconds, fail-safe
        site_context = _scrape_site_context(domain)

        title_hint = f'\nPage tab title: "{tab_title}"' if tab_title else ""

        template = self._get_prompt("evaluate_site_relevance", DEFAULT_EVALUATE_SITE_RELEVANCE)
        prompt = template.format(
            session_name=session_name,
            domain=domain,
            title_hint=title_hint,
            site_context=site_context,
        )

        ok, text, _ = self._post(prompt)
        if not ok:
            return False, ""  # Fail closed -- ask the user

        auto_allow = False
        reason = ""
        for line in text.split("\n"):
            upper = line.upper().strip()
            if upper.startswith("DECISION:"):
                verdict = upper.replace("DECISION:", "").strip()
                auto_allow = verdict == "AUTO_ALLOW"
            elif line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip() if ":" in line else line.strip()
        return auto_allow, reason
