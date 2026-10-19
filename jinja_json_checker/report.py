from __future__ import annotations

import html
from typing import List, Tuple

from .chars import INVISIBLE
from .checker import Result
from .issue import SEVERITY_ORDER, Issue

LABELS = {"error": "Ошибка", "warning": "Внимание", "info": "Заметка"}
MODE_NAMES = {
    "json": "JSON",
    "template": "шаблон Jinja2",
    "text": "текст",
}


def line_col(text: str, offset: int) -> Tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def summary(result: Result) -> str:
    kind = MODE_NAMES.get(result.mode, result.mode)
    e, w = len(result.errors), len(result.warnings)
    if not e and not w:
        return "Ошибок не найдено (%s)" % kind
    parts = []
    if e:
        parts.append("%d %s" % (e, _plural(e, "ошибка", "ошибки", "ошибок")))
    if w:
        parts.append("%d %s" % (w, _plural(w, "предупреждение", "предупреждения",
                                           "предупреждений")))
    return "%s: %s" % (kind[:1].upper() + kind[1:], ", ".join(parts))


def format_text(result: Result) -> str:
    text = result.text
    lines = text.split("\n")
    out = [summary(result)]
    for issue in result.issues:
        line, col = line_col(text, issue.offset)
        out.append("")
        if issue.length == 0:
            out.append("%s: %s" % (LABELS[issue.severity], issue.message))
            continue
        out.append("%s, строка %d, колонка %d: %s" % (
            LABELS[issue.severity], line, col, issue.message))
        src = lines[line - 1] if line - 1 < len(lines) else ""
        out.append("  %5d | %s" % (line, src))
        out.append("        | %s^" % "".join("\t" if c == "\t" else " " for c in src[:col - 1]))
    return "\n".join(out) + "\n"


CSS = """
body { font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0;
       color: #1d1d1f; background: #fafafa; }
header { padding: 16px 24px; border-bottom: 1px solid #ddd; background: #fff;
         position: sticky; top: 0; }
h1 { font-size: 18px; margin: 0 0 8px; }
h1.ok { color: #1a7f37; } h1.bad { color: #cf222e; } h1.warn { color: #9a6700; }
ul { margin: 0; padding-left: 20px; max-height: 30vh; overflow: auto; }
li { margin: 2px 0; }
li a { color: inherit; text-decoration: none; border-bottom: 1px dotted #888; }
.tag { font-weight: 600; } .tag.error { color: #cf222e; } .tag.warning { color: #9a6700; }
.tag.info { color: #57606a; }
pre { margin: 0; padding: 16px 0; font: 13px/1.5 Menlo, Consolas, monospace; tab-size: 4; }
.line { display: block; padding-right: 24px; }
.line:target { outline: 2px solid #0969da; }
.ln { display: inline-block; width: 4em; padding-right: 1em; text-align: right; color: #999;
      user-select: none; }
.line.error { background: #ffebe9; } .line.warning { background: #fff8c5; }
mark.error { background: #ff8182; color: #000; border-bottom: 2px solid #cf222e; }
mark.warning { background: #ffd33d; color: #000; }
mark.info { background: #ddf4ff; }
"""


def _severity_map(text: str, issues: List[Issue]) -> List[int]:
    sev = [-1] * len(text)
    for issue in issues:
        if issue.length == 0:
            continue
        level = SEVERITY_ORDER[issue.severity]
        for k in range(issue.offset, min(issue.offset + max(issue.length, 1), len(text))):
            sev[k] = max(sev[k], level)
    return sev


def format_html(result: Result) -> str:
    text = result.text
    names = {v: k for k, v in SEVERITY_ORDER.items()}
    sev = _severity_map(text, result.issues)

    line_sev = {}
    for issue in result.issues:
        if issue.length:
            line = line_col(text, issue.offset)[0]
            line_sev[line] = max(line_sev.get(line, -1), SEVERITY_ORDER[issue.severity])

    items = []
    for issue in result.issues:
        label = '<span class="tag %s">%s</span>' % (issue.severity, LABELS[issue.severity])
        if issue.length == 0:
            items.append("<li>%s: %s</li>" % (label, html.escape(issue.message)))
            continue
        line, col = line_col(text, issue.offset)
        items.append('<li>%s, <a href="#L%d">строка %d, колонка %d</a>: %s</li>' % (
            label, line, line, col, html.escape(issue.message)))

    body = []
    offset = 0
    for number, line_text in enumerate(text.split("\n"), 1):
        parts = []
        k = 0
        while k < len(line_text):
            level = sev[offset + k]
            j = k
            while j < len(line_text) and sev[offset + j] == level:
                j += 1
            raw = line_text[k:j]
            if level >= 0:
                if not raw.strip(" "):
                    raw = raw.replace(" ", "\u00b7")
                raw = "".join("\u00b7" if c in INVISIBLE else c for c in raw)
                chunk = '<mark class="%s">%s</mark>' % (names[level], html.escape(raw))
            else:
                chunk = html.escape(raw)
            parts.append(chunk)
            k = j
        cls = names[line_sev[number]] if number in line_sev else ""
        body.append('<span class="line %s" id="L%d"><span class="ln">%d</span>%s</span>' % (
            cls, number, number, "".join(parts)))
        offset += len(line_text) + 1

    if result.errors:
        h1 = "bad"
    elif result.warnings:
        h1 = "warn"
    else:
        h1 = "ok"
    return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Проверка синтаксиса</title>
<style>%s</style></head>
<body><header><h1 class="%s">%s</h1><ul>%s</ul></header>
<pre>%s</pre></body></html>
""" % (CSS, h1, html.escape(summary(result)), "".join(items), "".join(body))
