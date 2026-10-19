"""Command line entry point.

    python3 -m jinja_json_checker check [FILE] [--mode MODE] [--html PATH]
    python3 -m jinja_json_checker fix [FILE]
    python3 -m jinja_json_checker service-check [--clipboard]
    python3 -m jinja_json_checker service-fix [--clipboard]

Without FILE the text is read from stdin. ``service-*`` commands are meant for macOS
Quick Actions: they never fail with a non-zero exit code and report via notifications.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import macos
from .chars import fix_text
from .checker import MODES, check
from .report import format_html, format_text, summary


def read_input(path: Optional[str]) -> str:
    if path and path != "-":
        return Path(path).read_text(encoding="utf-8-sig")
    return sys.stdin.buffer.read().decode("utf-8", errors="replace")


def write_output(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def cmd_check(args: argparse.Namespace) -> int:
    result = check(read_input(args.file), args.mode)
    write_output(format_text(result))
    if args.html:
        Path(args.html).write_text(format_html(result), encoding="utf-8")
    return 0 if result.ok else 1


def cmd_fix(args: argparse.Namespace) -> int:
    fixed, count = fix_text(read_input(args.file))
    write_output(fixed)
    sys.stderr.write("Заменено символов: %d\n" % count)
    return 0


def cmd_service_check(args: argparse.Namespace) -> int:
    try:
        text = macos.paste() if args.clipboard else read_input(None)
        if not text.strip():
            macos.notify("Нет текста для проверки",
                         "Скопируйте текст" if args.clipboard else "Выделите текст")
            return 0
        result = check(text, args.mode)
        if not result.issues:
            macos.notify(summary(result))
            return 0
        macos.notify(summary(result), "Подробности открыты в браузере")
        macos.open_file(macos.write_report(format_html(result)))
    except Exception as e:  # report anything rather than fail silently inside Automator
        macos.notify("Ошибка проверки", "%s: %s" % (type(e).__name__, e))
    return 0


def cmd_service_fix(args: argparse.Namespace) -> int:
    text = ""
    try:
        text = macos.paste() if args.clipboard else read_input(None)
        fixed, count = fix_text(text)
        if args.clipboard:
            if count:
                macos.copy(fixed)
        else:
            write_output(fixed)
        if count:
            where = "в буфере обмена" if args.clipboard else ""
            macos.notify("Исправлено символов: %d" % count, where)
        else:
            macos.notify("Нечего исправлять", "Умных кавычек и невидимых символов нет")
    except Exception as e:
        if not args.clipboard:
            write_output(text)
        macos.notify("Ошибка исправления", "%s: %s" % (type(e).__name__, e))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jinja_json_checker",
        description="Проверка синтаксиса JSON и шаблонов Jinja2. Работает офлайн.")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    p = sub.add_parser("check", help="проверить текст и вывести отчёт")
    p.add_argument("file", nargs="?", help="файл; без него текст читается из stdin")
    p.add_argument("--mode", choices=MODES, default="auto")
    p.add_argument("--html", metavar="PATH", help="дополнительно сохранить HTML-отчёт")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("fix", help="заменить умные кавычки и невидимые символы")
    p.add_argument("file", nargs="?")
    p.set_defaults(func=cmd_fix)

    for name, func, help_text in (
        ("service-check", cmd_service_check, "для Quick Action: проверить и показать результат"),
        ("service-fix", cmd_service_fix, "для Quick Action: исправить кавычки"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--clipboard", action="store_true",
                       help="брать текст из буфера обмена, а не из stdin")
        if name == "service-check":
            p.add_argument("--mode", choices=MODES, default="auto")
        p.set_defaults(func=func)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
