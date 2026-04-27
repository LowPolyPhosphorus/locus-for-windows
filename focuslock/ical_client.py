"""iCal subscription fetcher.

Each feed is a public/secret .ics URL the user pasted in. We do a plain
HTTP GET, parse with `icalendar`, expand recurring events for the next N
days with `recurring-ical-events`, and yield NotionEvent rows so the
launcher can show them alongside Notion assignments.

Works with Google Calendar's "Secret iCal address," Apple iCloud calendars,
Outlook, Schoology, Canvas, and any other provider that emits iCalendar.
"""

import requests
from datetime import datetime, timedelta, timezone, date as _date
from typing import List, Tuple, Optional

import icalendar
import recurring_ical_events

from .notion_client import NotionEvent


class ICalClient:
    def __init__(self, feeds: List[Tuple[str, str]]):
        # feeds: list of (name, url). Name is the user's nickname for the
        # calendar; if empty we fall back to the calendar's X-WR-CALNAME.
        self.feeds = list(feeds)

    def get_upcoming_events(self, days: int = 14) -> List[NotionEvent]:
        out: List[NotionEvent] = []
        if not self.feeds:
            return out
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=days)
        for name, url in self.feeds:
            url = (url or "").strip()
            if not url:
                continue
            try:
                text = self._fetch(url)
            except Exception as e:
                print(f"[Locus] iCal fetch failed for {name or url}: {e}")
                continue
            try:
                cal = icalendar.Calendar.from_ical(text)
            except Exception as e:
                print(f"[Locus] iCal parse failed for {name or url}: {e}")
                continue

            label = name or self._calendar_name(cal) or "Calendar"
            try:
                instances = recurring_ical_events.of(cal).between(now, window_end)
            except Exception as e:
                # Some malformed feeds choke recurring_ical_events; fall
                # back to non-recurring iteration so the user still sees
                # the static events.
                print(f"[Locus] iCal recurrence expansion failed for {label}: {e}")
                instances = [c for c in cal.walk("VEVENT")]

            for ev in instances:
                parsed = self._parse_event(ev, label, now)
                if parsed:
                    out.append(parsed)
        return out

    def _fetch(self, url: str) -> str:
        # Some providers (Google Calendar especially) hand out webcal:// URLs.
        # Replace with https — the underlying server speaks HTTP regardless.
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        elif url.startswith("webcals://"):
            url = "https://" + url[len("webcals://"):]
        r = requests.get(url, timeout=15, headers={
            # Some servers serve a HTML page if no UA is set; pretend to be a browser.
            "User-Agent": "Locus/1.0 (+https://locus.app)"
        })
        r.raise_for_status()
        return r.text

    def _calendar_name(self, cal) -> Optional[str]:
        v = cal.get("X-WR-CALNAME") or cal.get("NAME")
        return str(v).strip() if v else None

    def _parse_event(self, ev, label: str, now: datetime) -> Optional[NotionEvent]:
        try:
            summary = str(ev.get("SUMMARY") or "").strip()
        except Exception:
            return None
        if not summary:
            return None

        dtstart = ev.get("DTSTART")
        if dtstart is None:
            return None
        start = dtstart.dt

        # Two cases: timed event (datetime) vs all-day (date).
        date_str = ""
        time_str = ""
        if isinstance(start, datetime):
            try:
                if start.tzinfo is None:
                    # Floating time — treat as local.
                    local = start.astimezone()
                else:
                    local = start.astimezone()
            except Exception:
                local = start
            date_str = local.strftime("%Y-%m-%d")
            time_str = local.strftime("%H:%M")
            # Skip events that already started more than an hour ago.
            try:
                if local.tzinfo is not None:
                    if (now - local.astimezone(timezone.utc)).total_seconds() > 3600:
                        return None
            except Exception:
                pass
        elif isinstance(start, _date):
            date_str = start.strftime("%Y-%m-%d")
            # Skip past all-day events (yesterday and earlier).
            if start < now.date():
                return None
        else:
            return None

        if not date_str:
            return None

        # Notes: prefer LOCATION, then DESCRIPTION. Trim to 200 to match Notion-side cap.
        loc = str(ev.get("LOCATION") or "").strip()
        desc = str(ev.get("DESCRIPTION") or "").strip()
        note = loc or desc
        if len(note) > 200:
            note = note[:200].rstrip() + "…"

        return NotionEvent(
            title=summary,
            class_name=label,
            event_type="Event",
            date=date_str,
            note=note,
            start_time=time_str,
            source="ical",
        )
