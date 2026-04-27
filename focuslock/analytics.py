"""Lightweight event logger for FocusLock analytics."""

import json
import os
import time

from .paths import EVENTS_PATH  # noqa: F401 — re-exported for tests


def log_event(type: str, **fields) -> None:
    record = json.dumps({"ts": time.time(), "type": type, **fields})
    try:
        with open(EVENTS_PATH, "a") as f:
            f.write(record + "\n")
    except Exception:
        pass


def compute_summary() -> dict:
    """Read the event log and return a pre-aggregated summary dict."""
    import datetime

    now = time.time()
    local_tz = datetime.timezone(datetime.timedelta(seconds=-time.timezone))

    def day_key(ts: float) -> str:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

    def today_str() -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d")

    def week_cutoff() -> float:
        dt = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        dt -= datetime.timedelta(days=dt.weekday())
        return dt.timestamp()

    today = today_str()
    week_start = week_cutoff()

    events = []
    try:
        with open(EVENTS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
    except FileNotFoundError:
        pass

    # ── accumulators ─────────────────────────────────────────────────────────
    focus_today = 0
    focus_week = 0
    focus_all = 0
    sessions_today = 0
    sessions_week = 0
    sessions_all = 0

    app_focus_today: dict = {}
    app_focus_week: dict = {}
    app_focus_all: dict = {}

    domain_visits: dict = {}     # all-time
    impulse_blocks: dict = {}    # domain/app → cancel+ai_denied count

    block_approved = 0
    block_denied = 0
    block_canceled = 0

    off_topic_all = 0
    off_topic_by_day: dict = {}

    session_lengths: list = []

    daily_focus: dict = {}       # date → seconds (last 14 days)
    hour_of_day: dict = {h: 0 for h in range(24)}

    days_with_sessions: set = set()

    # For open sessions (session_start without matching session_end)
    open_sessions: dict = {}     # session_name → start_ts

    for ev in events:
        ts = ev.get("ts", 0)
        etype = ev.get("type", "")
        d = day_key(ts)

        if etype == "session_start":
            sname = ev.get("session_name", "")
            open_sessions[sname] = ts
            days_with_sessions.add(d)
            hour = datetime.datetime.fromtimestamp(ts).hour
            hour_of_day[hour] = hour_of_day.get(hour, 0) + 1

        elif etype == "session_end":
            sname = ev.get("session_name", "")
            dur = ev.get("duration_seconds", 0)
            session_lengths.append(dur)
            open_sessions.pop(sname, None)

            if d == today:
                focus_today += dur
                sessions_today += 1
            if ts >= week_start:
                focus_week += dur
                sessions_week += 1
            focus_all += dur
            sessions_all += 1

            # Daily series (14-day window)
            cutoff14 = now - 14 * 86400
            if ts >= cutoff14:
                daily_focus[d] = daily_focus.get(d, 0) + dur

        elif etype == "app_focus":
            app = ev.get("app_name", "")
            dur = ev.get("duration_seconds", 0)
            if not app or not dur:
                continue
            app_focus_all[app] = app_focus_all.get(app, 0) + dur
            if d == today:
                app_focus_today[app] = app_focus_today.get(app, 0) + dur
            if ts >= week_start:
                app_focus_week[app] = app_focus_week.get(app, 0) + dur

        elif etype == "tab_visit":
            domain = ev.get("domain", "")
            if domain:
                domain_visits[domain] = domain_visits.get(domain, 0) + 1

        elif etype == "url_allowed":
            block_approved += 1

        elif etype == "url_denied":
            reason = ev.get("reason", "")
            domain = ev.get("domain", "")
            if reason == "cancel":
                block_canceled += 1
            else:
                block_denied += 1
            # Anything ending with the user failing to justify the block counts
            # as an impulse — cancel, ai_denied, no_reason, override_wrong.
            # Exclude background_silent_close (user moved on, not an impulse).
            if reason != "background_silent_close" and domain:
                impulse_blocks[domain] = impulse_blocks.get(domain, 0) + 1

        elif etype == "app_allowed":
            block_approved += 1

        elif etype == "app_denied":
            reason = ev.get("reason", "")
            app = ev.get("app_name", "")
            if reason == "cancel":
                block_canceled += 1
            else:
                block_denied += 1
            if app:
                impulse_blocks[app] = impulse_blocks.get(app, 0) + 1

        elif etype == "off_topic_detected":
            off_topic_all += 1
            off_topic_by_day[d] = off_topic_by_day.get(d, 0) + 1

    # ── In-progress session: count its elapsed time too ──────────────────────
    # A session_start without a session_end means the session is still running
    # (or the app crashed). Count its elapsed duration so KPIs update live.
    for sname, start_ts in open_sessions.items():
        if start_ts <= 0 or start_ts > now:
            continue
        dur = int(now - start_ts)
        if dur < 1:
            continue
        d = day_key(start_ts)
        focus_all += dur
        sessions_all += 1
        if d == today:
            focus_today += dur
            sessions_today += 1
            days_with_sessions.add(today)
        if start_ts >= week_start:
            focus_week += dur
            sessions_week += 1
        cutoff14 = now - 14 * 86400
        if start_ts >= cutoff14:
            daily_focus[d] = daily_focus.get(d, 0) + dur

    # ── Streak ────────────────────────────────────────────────────────────────
    streak = 0
    check = datetime.datetime.now().date()
    while True:
        if check.isoformat() in days_with_sessions:
            streak += 1
            check -= datetime.timedelta(days=1)
        else:
            break

    # ── Session histogram ─────────────────────────────────────────────────────
    buckets = {"0-15": 0, "15-30": 0, "30-60": 0, "60-120": 0, "120+": 0}
    for s in session_lengths:
        m = s / 60
        if m < 15:
            buckets["0-15"] += 1
        elif m < 30:
            buckets["15-30"] += 1
        elif m < 60:
            buckets["30-60"] += 1
        elif m < 120:
            buckets["60-120"] += 1
        else:
            buckets["120+"] += 1

    # ── Top lists ─────────────────────────────────────────────────────────────
    def top20(d: dict) -> list:
        return sorted(d.items(), key=lambda x: x[1], reverse=True)[:20]

    # ── Daily focus series for last 14 days ──────────────────────────────────
    daily_series = {}
    for i in range(14):
        d = (datetime.datetime.now() - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        daily_series[d] = daily_focus.get(d, 0)

    # ── Off-topic series for last 14 days ────────────────────────────────────
    off_topic_series = {}
    for i in range(14):
        d = (datetime.datetime.now() - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        off_topic_series[d] = off_topic_by_day.get(d, 0)

    # Exclude test/accidental sessions under 60s from the average so one-second
    # misclicks don't drag it down.
    long_sessions = [s for s in session_lengths if s >= 60]
    if long_sessions:
        avg_session = sum(long_sessions) // len(long_sessions)
    else:
        avg_session = (focus_all // sessions_all) if sessions_all > 0 else 0

    return {
        "generated_at": now,
        "focus_today": focus_today,
        "focus_week": focus_week,
        "focus_all": focus_all,
        "sessions_today": sessions_today,
        "sessions_week": sessions_week,
        "sessions_all": sessions_all,
        "avg_session_seconds": avg_session,
        "streak_days": streak,
        "app_focus_today": top20(app_focus_today),
        "app_focus_week": top20(app_focus_week),
        "app_focus_all": top20(app_focus_all),
        "domain_visits": top20(domain_visits),
        "impulse_blocks": sorted(impulse_blocks.items(), key=lambda x: x[1], reverse=True)[:10],
        "block_approved": block_approved,
        "block_denied": block_denied,
        "block_canceled": block_canceled,
        "off_topic_all": off_topic_all,
        "session_histogram": buckets,
        "daily_focus_series": daily_series,
        "hour_of_day": {str(h): c for h, c in hour_of_day.items()},
        "off_topic_series": off_topic_series,
    }
