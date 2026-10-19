"""Smart quotes and invisible characters that text editors and messengers sneak in."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .issue import Issue

# char -> (replacement, human-readable name)
SMART_QUOTES: Dict[str, Tuple[str, str]] = {
    "\u201c": ('"', "умная кавычка “"),
    "\u201d": ('"', "умная кавычка ”"),
    "\u201e": ('"', "нижняя кавычка „"),
    "\u201f": ('"', "кавычка ‟"),
    "\u2033": ('"', "знак ″ вместо кавычки"),
    "\u2018": ("'", "умный апостроф ‘"),
    "\u2019": ("'", "умный апостроф ’"),
    "\u201a": ("'", "нижний апостроф ‚"),
    "\u201b": ("'", "апостроф ‛"),
    "\u2032": ("'", "знак ′ вместо апострофа"),
}

INVISIBLE: Dict[str, Tuple[str, str]] = {
    "\u00a0": (" ", "неразрывный пробел"),
    "\u202f": (" ", "узкий неразрывный пробел"),
    "\u2007": (" ", "цифровой пробел"),
    "\u2009": (" ", "тонкий пробел"),
    "\u200a": (" ", "волосяной пробел"),
    "\u200b": ("", "пробел нулевой ширины"),
    "\u200c": ("", "невидимый разделитель"),
    "\u200d": ("", "невидимый соединитель"),
    "\u2060": ("", "невидимый соединитель слов"),
    "\ufeff": ("", "невидимая метка BOM"),
    "\u2028": ("\n", "разделитель строк Unicode"),
    "\u2029": ("\n", "разделитель абзацев Unicode"),
}

FIXABLE: Dict[str, Tuple[str, str]] = {**SMART_QUOTES, **INVISIBLE}

GUILLEMETS = {"\u00ab": "«", "\u00bb": "»"}


def describe(ch: str) -> str:
    if ch in FIXABLE:
        return FIXABLE[ch][1]
    return "символ U+%04X" % ord(ch)


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def find_chars(text: str) -> List[Issue]:
    issues: List[Issue] = []
    for i, ch in enumerate(text):
        if ch in SMART_QUOTES:
            right = SMART_QUOTES[ch][0]
            issues.append(Issue(
                "error",
                "%s вместо обычной %s. Исправит «Починить кавычки»" % (
                    cap(SMART_QUOTES[ch][1]), right),
                i, 1, "chars"))
        elif ch in INVISIBLE:
            issues.append(Issue(
                "warning",
                "%s. Исправит «Починить кавычки»" % cap(INVISIBLE[ch][1]),
                i, 1, "chars"))
    return issues


def neutralize(text: str) -> str:
    """Like fix_text, but keeps every offset: removed characters become spaces."""
    out = []
    for ch in text:
        if ch in FIXABLE:
            replacement = FIXABLE[ch][0]
            out.append(replacement if len(replacement) == 1 and replacement != "\n" else " ")
        else:
            out.append(ch)
    return "".join(out)


def fix_text(text: str) -> Tuple[str, int]:
    """Replace smart quotes and invisible characters. Returns (fixed text, replacements)."""
    out = []
    count = 0
    for ch in text:
        if ch in FIXABLE:
            out.append(FIXABLE[ch][0])
            count += 1
        else:
            out.append(ch)
    return "".join(out), count
