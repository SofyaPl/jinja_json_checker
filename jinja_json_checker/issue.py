from __future__ import annotations

from dataclasses import dataclass

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


@dataclass
class Issue:
    severity: str  # "error", "warning" or "info"
    message: str
    offset: int
    length: int = 1
    source: str = ""  # "chars", "jinja", "json" or "text"
