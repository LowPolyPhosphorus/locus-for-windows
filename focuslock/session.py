"""Focus session state."""
from dataclasses import dataclass, field
from typing import List


@dataclass
class FocusSession:
    title: str
    class_name: str
    event_type: str
    open_apps: List[str] = field(default_factory=list)
    allow_apps: List[str] = field(default_factory=list)    # allowed on top of ALWAYS_ALLOWED
    allow_domains: List[str] = field(default_factory=list) # allowed without explanation
    blocked_attempts: int = 0

    @property
    def display_name(self) -> str:
        name = self.class_name or self.title
        if self.event_type:
            return f"{name} — {self.event_type}"
        return name
