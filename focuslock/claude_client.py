"""AI evaluator — calls the Locus Cloudflare Worker, which forwards to Hack Club AI.

The real upstream key is held as a Worker secret, not shipped in this binary.
"""

import json
import os
import uuid
import requests

from .paths import CONFIG_PATH, APP_SUPPORT_DIR

# Public endpoint of our Cloudflare Worker. Safe to hardcode — the Worker
# itself enforces rate limits and holds the real Hack Club key as a secret.
PROXY_URL = "https://locus-proxy.locus-proxy.workers.dev/"
DEVICE_ID_PATH = os.path.join(APP_SUPPORT_DIR, "device_id")


def _device_id() -> str:
    """Random stable ID per install. Used by the Worker for rate limiting."""
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
- If the session name suggests a dev/tech/creative project (e.g. contains words like "hack", "project", "game", "build", "code", "app", "dev"), be MORE lenient about technical tools — Steam (for testing games), Unity, VS Code, terminals, browsers, etc. are likely legitimate.
- If the session name suggests academic work (e.g. "math homework", "essay", "study"), be stricter about unrelated apps.
- Give the student the benefit of the doubt. Only deny if the reason is clearly unrelated or obviously an excuse.
- Be more strict for entertainment apps with no plausible work use (Netflix, TikTok, etc.).

Respond in exactly this format:
DECISION: APPROVED or DENIED
REASON: One sentence."""

DEFAULT_EVALUATE_SITE_RELEVANCE = """A high school student is in a focus session: **{session_name}**

They just visited: **{domain}**{title_hint}

Is this website OBVIOUSLY and CLEARLY relevant to their study session?

AUTO-ALLOW examples (don't bother asking):
- Calculator/Desmos during Math
- Google searching subject-related terms
- Khan Academy during any study session
- SpanishDict during Spanish
- Stack Overflow during CSP/coding
- Dictionary/Wikipedia for research
- Schoology

ASK examples (need justification):
- YouTube (could be tutorials OR entertainment)
- Reddit, Twitter, Discord, TikTok
- Netflix, Twitch, gaming sites
- Any social media
- Shopping sites
- Sites with no clear connection to the subject

Only return AUTO_ALLOW when there is NO reasonable doubt.
When in doubt, return ASK.

Respond in exactly this format:
DECISION: AUTO_ALLOW or ASK
REASON: One sentence."""

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
                return False, "", "rate limited — try again in a bit"
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
                # Exact match so "NOT APPROVED" / "DISAPPROVED" don't slip through.
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
                # Exact match — "OFF-TOPIC" contains no "RELEVANT" substring so
                # this mostly worked before, but be explicit.
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
        """Pre-screen: is this site obviously relevant to the session?"""
        title_hint = f'\nThe page title is: "{tab_title}"' if tab_title else ""
        template = self._get_prompt("evaluate_site_relevance", DEFAULT_EVALUATE_SITE_RELEVANCE)
        prompt = template.format(
            session_name=session_name,
            domain=domain,
            title_hint=title_hint,
        )

        ok, text, _ = self._post(prompt)
        if not ok:
            return False, ""  # Fail closed

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
