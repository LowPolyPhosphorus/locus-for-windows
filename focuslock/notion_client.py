"""Fetch assignments/events from the Notion Planner database."""

import requests
from datetime import date
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class NotionEvent:
    title: str
    class_name: str     # e.g. "CSP", "Math" — empty for non-Notion sources
    event_type: str     # "Assignment", "Exam", "Deadline", "Event"
    date: str           # "YYYY-MM-DD"
    note: str
    start_time: str = ""  # "HH:MM" 24h, empty for date-only events
    source: str = "notion"  # "notion" | "google"


class NotionClient:
    BASE = "https://api.notion.com/v1"
    VERSION = "2022-06-28"

    def __init__(self, api_key: str, database_id: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": self.VERSION,
            "Content-Type": "application/json",
        }
        self.database_id = database_id.replace("-", "")

    def get_upcoming_events(self) -> List[NotionEvent]:
        """Return all events from today onwards, sorted by date."""
        today = date.today().isoformat()
        all_pages = self._search_all_pages()
        events = [self._parse(p) for p in all_pages]
        events = [e for e in events if e and e.date >= today]
        events.sort(key=lambda e: e.date)
        return events

    def _search_all_pages(self) -> list:
        results = []
        payload: dict = {
            "filter": {"value": "page", "property": "object"},
            "page_size": 100,
        }
        while True:
            resp = requests.post(
                f"{self.BASE}/search",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            if not resp.ok:
                print(f"[FocusLock] Notion error: {resp.text}")
            resp.raise_for_status()
            data = resp.json()

            for page in data.get("results", []):
                parent = page.get("parent", {})
                parent_id = parent.get("database_id", "").replace("-", "")
                if parent_id == self.database_id:
                    results.append(page)

            if not data.get("has_more"):
                break
            payload["start_cursor"] = data["next_cursor"]

        return results

    def _parse(self, page: dict) -> Optional[NotionEvent]:
        try:
            props = page["properties"]

            title_parts = props.get("Event", {}).get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts).strip()
            if not title:
                return None

            class_sel = props.get("Class", {}).get("select") or {}
            class_name = class_sel.get("name", "")

            type_sel = props.get("Event Type", {}).get("select") or {}
            event_type = type_sel.get("name", "")

            date_val = props.get("Date", {}).get("date") or {}
            event_date = (date_val.get("start") or "")[:10]

            # Skip completed items (checkbox property with empty-string name)
            completed = props.get("", {}).get("checkbox", False)
            if completed:
                return None

            note_parts = props.get("Note", {}).get("rich_text", [])
            note = "".join(t.get("plain_text", "") for t in note_parts).strip()

            return NotionEvent(
                title=title,
                class_name=class_name,
                event_type=event_type,
                date=event_date,
                note=note,
            )
        except Exception as e:
            print(f"[FocusLock] Parse error: {e}")
            return None
