"""Small JSON parser that reports errors with positions and plain-language messages.

Unlike ``json.loads`` it also reports duplicate keys and, for templates, tolerates
missing or trailing commas at the edges of ``{% if %}`` / ``{% for %}`` blocks,
where the real result depends on template logic.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .chars import GUILLEMETS, INVISIBLE, SMART_QUOTES, cap, describe
from .issue import Issue

NUMBER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
DIGITS = "0123456789"
WORD_RE = re.compile(r"[A-Za-z_\u0400-\u04FF][\w\u0400-\u04FF]*")
WHITESPACE = " \t\n\r"
ESCAPES = '"\\/bfnrtu'
PYTHON_LITERALS = {"True": "true", "False": "false", "None": "null"}
CLOSING = {"{": "}", "[": "]"}
IDENTITY_FIELDS = ("key", "name", "id")


class _Stop(Exception):
    pass


class _Parser:
    def __init__(self, text: str, conditional: Optional[List[bool]] = None) -> None:
        self.text = text
        self.n = len(text)
        self.cond = conditional or [False] * self.n
        self.i = 0
        self.issues: List[Issue] = []
        self.open: List[Tuple[str, int]] = []
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", text)]

    # -- helpers -------------------------------------------------------------

    def line(self, offset: int) -> int:
        return _bisect(self.line_starts, offset) + 1

    def error(self, message: str, offset: int, length: int = 1) -> None:
        self.issues.append(Issue("error", message, offset, length, "json"))
        raise _Stop()

    def warning(self, message: str, offset: int, length: int = 1) -> None:
        self.issues.append(Issue("warning", message, offset, length, "json"))

    def peek(self) -> str:
        return self.text[self.i] if self.i < self.n else ""

    def skip_ws(self) -> None:
        while self.i < self.n:
            ch = self.text[self.i]
            if ch in WHITESPACE:
                self.i += 1
            elif self.text.startswith("//", self.i) or self.text.startswith("/*", self.i):
                self.error("Комментарии в JSON не допускаются", self.i, 2)
            else:
                break

    def unclosed(self) -> None:
        bracket, pos = self.open[-1]
        self.error("Не закрыта «%s» из строки %d: нет «%s»" % (
            bracket, self.line(pos), CLOSING[bracket]), pos)

    def unexpected(self, expected: str) -> None:
        i = self.i
        ch = self.peek()
        if not ch:
            if self.open:
                self.unclosed()
            self.error("Текст закончился, а ожидалось %s" % expected, max(self.n - 1, 0))
        if ch in SMART_QUOTES:
            self.error("%s вместо обычной %s. Исправит «Починить кавычки»" % (
                cap(describe(ch)), SMART_QUOTES[ch][0]), i)
        if ch in GUILLEMETS:
            self.error("Кавычка-ёлочка %s вместо обычной \"" % ch, i)
        if ch == "'":
            self.error("В JSON строки и ключи пишутся в двойных кавычках \", а не в одинарных '", i)
        if ch in INVISIBLE:
            self.error("%s: невидимый символ, JSON его не принимает. Исправит «Починить кавычки»"
                       % cap(describe(ch)), i)
        if ch == ",":
            self.error("Лишняя запятая", i)
        m = WORD_RE.match(self.text, i)
        if m:
            word = m.group()
            if word in PYTHON_LITERALS:
                self.error("В JSON пишется %s, а не %s" % (PYTHON_LITERALS[word], word),
                           i, len(word))
            if expected == "ключ":
                self.error("Ключ должен быть в двойных кавычках: \"%s\"" % word, i, len(word))
            self.error("Непонятное слово «%s»: строки в JSON берутся в двойные кавычки" % word,
                       i, len(word))
        self.error("Неожиданный символ «%s», ожидалось %s" % (ch, expected), i)

    def missing_comma_ok(self, prev_end: int) -> bool:
        return self.cond[self.i] or (prev_end > 0 and self.cond[prev_end - 1])

    # -- grammar -------------------------------------------------------------

    def parse(self) -> None:
        self.skip_ws()
        if self.i >= self.n:
            self.error("Пустой текст: нечего проверять", 0)
        self.value()
        self.skip_ws()
        if self.i < self.n:
            ch = self.peek()
            hint = ""
            if ch in "]}":
                hint = ": лишняя закрывающая скобка «%s»" % ch
            elif ch in "{[":
                hint = ": похоже, JSON вставлен дважды или потеряна запятая"
            self.error("Лишний текст после конца JSON" + hint, self.i)

    def value(self) -> Any:
        """Parse a value. Returns objects as {key: (value, offset)}, strings as str, else None."""
        self.skip_ws()
        ch = self.peek()
        if ch == "{":
            return self.obj()
        if ch == "[":
            self.arr()
        elif ch == '"':
            return self.string()
        elif ch and ch in "-" + DIGITS:
            self.number()
        elif ch and ch in "tfn" and WORD_RE.match(self.text, self.i):
            self.literal()
        else:
            self.unexpected("значение")
        return None

    def obj(self) -> Dict[str, Tuple[Any, int]]:
        self.open.append(("{", self.i))
        self.i += 1
        keys: Dict[str, int] = {}
        members: Dict[str, Tuple[Any, int]] = {}
        self.skip_ws()
        if self.peek() == "}":
            self.i += 1
            self.open.pop()
            return members
        while True:
            self.skip_ws()
            if self.peek() != '"':
                self.unexpected("ключ")
            key_pos = self.i
            key = self.string()
            if key in keys:
                self.warning("Ключ \"%s\" повторяется (первый раз — в строке %d)" % (
                    key, self.line(keys[key])), key_pos, self.i - key_pos)
            else:
                keys[key] = key_pos
            self.skip_ws()
            if self.peek() != ":":
                if not self.peek():
                    self.unclosed()
                self.error("После ключа \"%s\" нужно двоеточие «:»" % key, self.i)
            self.i += 1
            self.skip_ws()
            value_pos = self.i
            members[key] = (self.value(), value_pos)
            if self.after_item("}", key_pos):
                return members

    def arr(self) -> None:
        self.open.append(("[", self.i))
        self.i += 1
        seen: Dict[Tuple[str, str], int] = {}
        self.skip_ws()
        if self.peek() == "]":
            self.i += 1
            self.open.pop()
            return
        while True:
            self.skip_ws()
            item_pos = self.i
            item = self.value()
            if isinstance(item, dict):
                self.check_identity(item, seen)
            if self.after_item("]", item_pos):
                return

    def check_identity(self, item: Dict[str, Tuple[Any, int]],
                       seen: Dict[Tuple[str, str], int]) -> None:
        """Warn when objects in one array repeat the same "key"/"name"/"id" value."""
        for field in IDENTITY_FIELDS:
            value, pos = item.get(field, (None, 0))
            if not isinstance(value, str):
                continue
            first = seen.get((field, value))
            if first is None:
                seen[(field, value)] = pos
            else:
                length = self.text.find('"', pos + 1) + 1 - pos
                self.warning("Элемент с \"%s\": \"%s\" повторяется в списке (первый раз — в строке %d)"
                             % (field, value, self.line(first)), pos, max(length, 1))

    def after_item(self, close: str, item_pos: int) -> bool:
        """Handle what follows an object member or array item. True when container closed."""
        prev_end = self.i
        self.skip_ws()
        ch = self.peek()
        if ch == ",":
            comma = self.i
            self.i += 1
            self.skip_ws()
            if self.peek() == close:
                if not self.cond[comma]:
                    self.error("Лишняя запятая перед «%s»" % close, comma)
                self.i += 1
                self.open.pop()
                return True
            return False
        if ch == close:
            self.i += 1
            self.open.pop()
            return True
        if not ch:
            self.unclosed()
        if ch in "]}":
            bracket, pos = self.open[-1]
            self.error("Ожидалась «%s» (закрывает «%s» из строки %d), а стоит «%s»" % (
                close, bracket, self.line(pos), ch), self.i)
        if ch in '"{[-0123456789tfn' and self.missing_comma_ok(prev_end):
            return False
        if close == "}" and ch in "{[":
            bracket, pos = self.open[-1]
            self.error("Здесь начинается новый %s, а объект «{» из строки %d не закрыт: "
                       "пропущена «}» или запятая" % ("объект" if ch == "{" else "список",
                                                      self.line(pos)), self.i)
        if ch in '"{[' + DIGITS:
            self.error("Пропущена запятая после этого значения", prev_end - 1)
        self.unexpected("запятая или «%s»" % close)
        return False

    def string(self) -> str:
        start = self.i
        self.i += 1
        out = []
        while True:
            if self.i >= self.n:
                self.error("Строка не закрыта кавычкой \"", start)
            ch = self.text[self.i]
            if ch == '"':
                self.i += 1
                return "".join(out)
            if ch == "\n":
                smart = [c for c in self.text[start:self.i] if c in SMART_QUOTES]
                hint = (": внутри есть %s, возможно, она должна была закрыть строку"
                        % describe(smart[0])) if smart else ": пропущена закрывающая кавычка \"?"
                self.error("Строка не закрыта до конца строки" + hint, start)
            if ch == "\t":
                self.error("Табуляция внутри строки недопустима в JSON: замените на пробел или \\t",
                           self.i)
            if ord(ch) < 0x20:
                self.error("Управляющий символ U+%04X внутри строки" % ord(ch), self.i)
            if ch == "\\":
                nxt = self.text[self.i + 1:self.i + 2]
                if not nxt or nxt not in ESCAPES:
                    self.error("Неправильная escape-последовательность «\\%s»: обратный слэш "
                               "в JSON пишется как \\\\" % nxt, self.i, 2)
                if nxt == "u":
                    hexpart = self.text[self.i + 2:self.i + 6]
                    if not re.fullmatch(r"[0-9a-fA-F]{4}", hexpart):
                        self.error("После \\u нужны 4 шестнадцатеричные цифры", self.i, 2)
                    out.append(chr(int(hexpart, 16)))
                    self.i += 6
                    continue
                out.append(nxt)
                self.i += 2
                continue
            out.append(ch)
            self.i += 1

    def number(self) -> None:
        m = NUMBER_RE.match(self.text, self.i)
        if not m:
            self.error("Неправильное число", self.i)
        end = m.end()
        if end < self.n and (self.text[end].isalnum() or self.text[end] in "._"):
            if self.text[self.i:end].lstrip("-") == "0" and self.text[end] in DIGITS:
                self.error("Число не может начинаться с 0", self.i, end - self.i + 1)
            self.error("Неправильное число", self.i, end - self.i + 1)
        self.i = end

    def literal(self) -> None:
        m = WORD_RE.match(self.text, self.i)
        word = m.group() if m else ""
        if word in ("true", "false", "null"):
            self.i += len(word)
        else:
            self.unexpected("значение")


def _bisect(starts: List[int], offset: int) -> int:
    lo, hi = 0, len(starts)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid
    return lo


def parse(text: str, conditional: Optional[List[bool]] = None) -> List[Issue]:
    """Parse JSON and return found issues: at most one error plus warnings."""
    p = _Parser(text, conditional)
    try:
        p.parse()
    except _Stop:
        pass
    return p.issues
