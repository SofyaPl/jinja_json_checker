"""Offline syntax checker for JSON and Jinja2 templates that produce JSON."""

from .checker import Issue, Result, check
from .chars import fix_text

__all__ = ["Issue", "Result", "check", "fix_text"]
__version__ = "0.1.0"
