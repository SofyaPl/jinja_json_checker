from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set

from . import jsonparse, template
from .chars import find_chars, neutralize
from .issue import SEVERITY_ORDER, Issue

MODES = ("auto", "json", "template")

JSON_BLOCKED = ("JSON ещё не проверен: сначала исправьте ошибки в тегах шаблона. "
                "После этого могут найтись новые ошибки")
JSON_STOPPED = ("Проверка JSON остановилась на первой ошибке. "
                "После её исправления могут найтись следующие")
NOT_JSON = "Это не похоже на JSON или шаблон: проверены только кавычки и невидимые символы"
MISSING_OPEN = "Не хватает «{» в начале: текст начинается сразу с ключа"
KEY_START_RE = re.compile(r"[ \t\r\n]*\"(?:[^\"\\\n]|\\.)*\"[ \t\r\n]*:")


@dataclass
class Result:
    mode: str
    text: str
    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _starts_with_key(masked: str) -> bool:
    return bool(KEY_START_RE.match(masked))


def detect_mode(text: str, masked: str) -> str:
    stripped = masked.strip(" \t\r\n")
    if stripped[:1] in ("{", "[") or stripped[-1:] in ("}", "]") or _starts_with_key(masked):
        return "json"
    if masked != text:
        return "template"
    return "text"


def _check_json(analysis: template.Analysis, char_offsets: Set[int]) -> List[Issue]:
    if _starts_with_key(analysis.masked):
        lead = len(analysis.masked) - len(analysis.masked.lstrip(" \t\r\n"))
        return [Issue("error", MISSING_OPEN, lead, 1, "json")]
    found = jsonparse.parse(analysis.masked, analysis.conditional)
    error = next((i for i in found if i.severity == "error"), None)
    if error is None or error.offset not in char_offsets:
        return found
    # Parsing stopped at a smart quote or invisible character, which is reported
    # anyway. Parse again as if they were fixed to find the errors behind them.
    return [error] + jsonparse.parse(neutralize(analysis.masked), analysis.conditional)


def check(text: str, mode: str = "auto") -> Result:
    text = text.replace("\r\n", "\n")
    if mode not in MODES:
        raise ValueError("unknown mode: %s" % mode)

    analysis = template.analyze(text)
    if mode == "auto":
        mode = detect_mode(text, analysis.masked)

    issues = find_chars(text)
    issues.extend(analysis.issues)
    jinja_errors = any(i.severity == "error" for i in analysis.issues)

    if analysis.has_template and not jinja_errors:
        extra = template.jinja2_check(text)
        if extra:
            issues.append(extra)
            jinja_errors = True

    if mode == "json":
        if jinja_errors:
            issues.append(Issue("info", JSON_BLOCKED, 0, 0, "json"))
        else:
            char_offsets = {i.offset for i in issues if i.source == "chars"}
            found = _check_json(analysis, char_offsets)
            issues.extend(found)
            if any(i.severity == "error" and i.offset not in char_offsets for i in found):
                issues.append(Issue("info", JSON_STOPPED, 0, 0, "json"))
    elif mode == "text":
        issues.append(Issue("info", NOT_JSON, 0, 0, "text"))

    # A bad character also breaks the syntax at the same spot: report it once.
    char_issues = {i.offset: i for i in issues if i.source == "chars"}
    deduped = []
    for issue in issues:
        twin = char_issues.get(issue.offset)
        if twin is not None and issue.source == "json" and issue.severity != "info":
            if twin.severity == "error":
                continue
            twin.severity, twin.message = issue.severity, issue.message
            continue
        deduped.append(issue)

    deduped.sort(key=lambda i: (i.severity == "info", i.offset, -SEVERITY_ORDER[i.severity]))
    return Result(mode, text, deduped)
