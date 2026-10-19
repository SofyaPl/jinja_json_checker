"""Jinja2 tag scanner.

Finds ``{{ }}``, ``{% %}`` and ``{# #}`` tags, checks that they are closed and that
block tags (if/for/...) are balanced, and builds a *masked* copy of the text where
every tag is blanked out so the rest can be parsed as JSON. The masked text has
exactly the same length and line breaks as the original, so offsets match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .issue import Issue

OPENER_RE = re.compile(r"\{[{%#]")
NAME_RE = re.compile(r"\s*([A-Za-z_]\w*)")
ENDRAW_RE = re.compile(r"\{%[-+]?\s*endraw\s*[-+]?%\}")

CLOSERS = {"{{": "}}", "{%": "%}"}
BRACKETS = {"(": ")", "[": "]", "{": "}"}

BLOCKS = {
    "if", "for", "macro", "call", "filter", "block", "with",
    "autoescape", "trans", "set",
}
MIDDLE = {"elif": {"if"}, "else": {"if", "for"}, "pluralize": {"trans"}}
STANDALONE = {
    "extends", "include", "import", "from", "do", "break", "continue",
    "raw", "endraw",
}


@dataclass
class Tag:
    kind: str  # "expr", "stmt" or "comment"
    start: int
    end: int
    body: str = ""
    name: str = ""


@dataclass
class Analysis:
    has_template: bool
    tags: List[Tag]
    issues: List[Issue]
    masked: str
    conditional: List[bool] = field(default_factory=list)


def _err(message: str, offset: int, length: int = 2, severity: str = "error") -> Issue:
    return Issue(severity, message, offset, length, "jinja")


def _strip_ws_control(body: str) -> str:
    if body[:1] in "-+":
        body = body[1:]
    if body[-1:] in "-+":
        body = body[:-1]
    return body


def _scan_tag(text: str, start: int, issues: List[Issue]) -> Tuple[Optional[Tag], int]:
    """Scan an expression or statement tag. Returns (tag or None, position to continue)."""
    opener = text[start:start + 2]
    closer = CLOSERS[opener]
    wrong_closer = "%}" if closer == "}}" else "}}"
    n = len(text)
    pos = start + 2
    quote = None
    stack: List[Tuple[str, int]] = []

    while pos < n:
        ch = text[pos]
        if quote:
            if ch == "\\":
                pos += 2
                continue
            if ch == quote:
                quote = None
            pos += 1
            continue

        pair = text[pos:pos + 2]
        if pair in ("{{", "{%", "{#"):
            issues.append(_err(
                "Тег «%s» не закрыт: перед «%s» нет «%s»" % (opener, pair, closer), start))
            return None, pos
        if pair == "%}" or (pair == "}}" and not stack):
            if pair != closer:
                issues.append(_err(
                    "Тег открыт «%s», а закрыт «%s»" % (opener, wrong_closer),
                    start, pos + 2 - start))
                return Tag("expr" if opener == "{{" else "stmt", start, pos + 2), pos + 2
            if stack:
                open_ch, open_pos = stack[-1]
                issues.append(_err(
                    "Внутри тега не закрыта скобка «%s»" % open_ch, open_pos, 1))
            return _finish_tag(text, start, pos + 2, issues), pos + 2

        if ch in "\"'":
            quote = ch
        elif ch in BRACKETS:
            stack.append((ch, pos))
        elif ch in ")]}":
            if stack and BRACKETS[stack[-1][0]] == ch:
                stack.pop()
            elif pair == closer:
                open_ch, open_pos = stack[-1]
                issues.append(_err(
                    "Внутри тега не закрыта скобка «%s»" % open_ch, open_pos, 1))
                return Tag("expr" if opener == "{{" else "stmt", start, pos + 2), pos + 2
            elif ch == "}" and not stack:
                issues.append(_err(
                    "Тег «%s» закрыт одной «}», а нужно «%s»" % (opener, closer),
                    start, pos + 1 - start))
                return Tag("expr" if opener == "{{" else "stmt", start, pos + 1), pos + 1
            else:
                issues.append(_err("Лишняя скобка «%s» внутри тега" % ch, pos, 1))
        pos += 1

    if quote:
        issues.append(_err(
            "Тег «%s» не закрыт: внутри не закрыта кавычка %s" % (opener, quote), start))
    else:
        issues.append(_err("Тег «%s» не закрыт: нет «%s»" % (opener, closer), start))
    return None, n


def _finish_tag(text: str, start: int, end: int, issues: List[Issue]) -> Tag:
    opener = text[start:start + 2]
    body = _strip_ws_control(text[start + 2:end - 2])
    if opener == "{{":
        stripped = body.strip()
        if not stripped:
            issues.append(_err("Пустое выражение «{{ }}»", start, end - start))
        elif stripped.endswith("|"):
            issues.append(_err("После «|» не указан фильтр", start, end - start))
        elif stripped.startswith("|"):
            issues.append(_err("Перед «|» нет значения", start, end - start))
        return Tag("expr", start, end, body)

    m = NAME_RE.match(body)
    name = m.group(1) if m else ""
    if not name:
        issues.append(_err("Пустой или неправильный тег «{% %}»", start, end - start))
    return Tag("stmt", start, end, body, name)


def scan_tags(text: str) -> Tuple[List[Tag], List[Issue]]:
    tags: List[Tag] = []
    issues: List[Issue] = []
    pos = 0
    while True:
        m = OPENER_RE.search(text, pos)
        if not m:
            break
        start = m.start()
        if m.group() == "{#":
            close = text.find("#}", start + 2)
            if close < 0:
                issues.append(_err("Комментарий «{#» не закрыт: нет «#}»", start))
                break
            tags.append(Tag("comment", start, close + 2))
            pos = close + 2
            continue

        tag, pos = _scan_tag(text, start, issues)
        if tag is None:
            continue
        tags.append(tag)
        if tag.kind == "stmt" and tag.name == "raw":
            end_m = ENDRAW_RE.search(text, tag.end)
            if not end_m:
                issues.append(_err("«{% raw %}» не закрыт: нет «{% endraw %}»", tag.start,
                                   tag.end - tag.start))
                break
            tags.append(Tag("stmt", end_m.start(), end_m.end(), "endraw", "endraw"))
            pos = end_m.end()
    return tags, issues


def _is_block_set(body: str) -> bool:
    """``{% set x = 1 %}`` is standalone, ``{% set x %}...{% endset %}`` is a block."""
    depth = 0
    quote = None
    for ch in body:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "=" and depth == 0:
            return False
    return True


@dataclass
class _Frame:
    name: str
    tag: Tag
    last: Tag
    in_else_branch: bool = False
    seen_else: bool = False
    first_branch_end: Optional[int] = None


def _tag_label(name: str) -> str:
    return "{%% %s %%}" % name


def match_blocks(tags: List[Tag]) -> Tuple[List[Issue], List[Tuple[int, int]], List[Tuple[int, int]]]:
    """Returns (issues, removed regions, conditional regions).

    Removed regions are elif/else branches: only the first branch of a condition is
    kept for the JSON check. Conditional regions are bodies of if/for, where commas
    at the edges depend on template logic and can't be verified statically.
    """
    issues: List[Issue] = []
    removed: List[Tuple[int, int]] = []
    conditional: List[Tuple[int, int]] = []
    stack: List[_Frame] = []

    def close(frame: _Frame, end_tag: Tag) -> None:
        if frame.in_else_branch:
            removed.append((frame.last.end, end_tag.start))
        first_end = frame.first_branch_end if frame.first_branch_end is not None else end_tag.start
        if frame.name in ("if", "for"):
            conditional.append((frame.tag.end, first_end))

    for tag in tags:
        if tag.kind != "stmt" or not tag.name:
            continue
        name = tag.name
        size = tag.end - tag.start

        if name in BLOCKS and (name != "set" or _is_block_set(NAME_RE.sub("", tag.body, 1))):
            stack.append(_Frame(name, tag, tag))
        elif name in MIDDLE:
            if stack and stack[-1].name in MIDDLE[name]:
                frame = stack[-1]
                if frame.seen_else:
                    issues.append(_err("«%s» после «{%% else %%}»" % _tag_label(name),
                                       tag.start, size))
                if frame.in_else_branch:
                    removed.append((frame.last.end, tag.start))
                if frame.first_branch_end is None:
                    frame.first_branch_end = tag.start
                frame.last = tag
                frame.in_else_branch = True
                frame.seen_else = frame.seen_else or name == "else"
            else:
                parents = " или ".join("«%s»" % _tag_label(p) for p in sorted(MIDDLE[name]))
                issues.append(_err("«%s» без открывающего %s" % (_tag_label(name), parents),
                                   tag.start, size))
        elif name.startswith("end") and name[3:] in BLOCKS:
            opener = name[3:]
            idx = next((k for k in range(len(stack) - 1, -1, -1) if stack[k].name == opener), None)
            if idx is None:
                issues.append(_err("Лишний «%s»: нет открывающего «%s»" % (
                    _tag_label(name), _tag_label(opener)), tag.start, size))
                continue
            for frame in stack[idx + 1:]:
                issues.append(_err("Не закрыт «%s»: перед «%s» нужен «%s»" % (
                    _tag_label(frame.name), _tag_label(name), _tag_label("end" + frame.name)),
                    frame.tag.start, frame.tag.end - frame.tag.start))
            close(stack[idx], tag)
            del stack[idx:]
        elif name in STANDALONE or name in BLOCKS:
            pass
        else:
            issues.append(_err("Неизвестный тег «%s» — возможно, опечатка" % _tag_label(name),
                               tag.start, size, "warning"))

    for frame in stack:
        issues.append(_err("Не закрыт «%s»: нет «%s»" % (
            _tag_label(frame.name), _tag_label("end" + frame.name)),
            frame.tag.start, frame.tag.end - frame.tag.start))
    return issues, removed, conditional


def _json_string_state(chars: List[str]) -> List[bool]:
    state = [False] * len(chars)
    in_str = False
    escaped = False
    for i, ch in enumerate(chars):
        state[i] = in_str
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"' or ch == "\n":
                in_str = False
        elif ch == '"':
            in_str = True
    return state


def analyze(text: str) -> Analysis:
    tags, issues = scan_tags(text)
    block_issues, removed, cond_regions = match_blocks(tags)
    issues.extend(block_issues)

    n = len(text)
    chars = list(text)
    dropped = [False] * n

    def blank(a: int, b: int, drop: bool = False) -> None:
        for k in range(a, b):
            if chars[k] != "\n":
                chars[k] = " "
            if drop:
                dropped[k] = True

    for tag in tags:
        blank(tag.start, tag.end)
    for a, b in removed:
        blank(a, b, drop=True)

    conditional = [False] * n
    for a, b in cond_regions:
        for k in range(a, b):
            conditional[k] = True

    # Put a JSON placeholder where an expression stands outside a JSON string:
    # "" when it is used as a key, 0 otherwise. Adjacent expressions share one.
    in_str = _json_string_state(chars)
    groups: List[List[int]] = []
    for tag in tags:
        if tag.kind != "expr" or dropped[tag.start]:
            continue
        if groups and not "".join(chars[groups[-1][1]:tag.start]).strip():
            groups[-1][1] = tag.end
        else:
            groups.append([tag.start, tag.end])
    for start, end in groups:
        if in_str[start]:
            continue
        nxt = end
        while nxt < n and chars[nxt].isspace():
            nxt += 1
        if nxt < n and chars[nxt] == ":":
            chars[start], chars[start + 1] = '"', '"'
        else:
            chars[start] = "0"

    return Analysis(bool(tags) or bool(issues), tags, issues, "".join(chars), conditional)


def jinja2_check(text: str) -> Optional[Issue]:
    """Extra check with the real Jinja2 parser, if the library happens to be installed."""
    try:
        import jinja2  # type: ignore
    except ImportError:
        return None
    try:
        jinja2.Environment().parse(text)
    except jinja2.TemplateSyntaxError as e:
        line = max((e.lineno or 1) - 1, 0)
        offset = 0
        for _ in range(line):
            nl = text.find("\n", offset)
            if nl < 0:
                break
            offset = nl + 1
        return _err("Jinja2: %s" % e.message, offset, 1)
    return None
