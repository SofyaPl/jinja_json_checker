import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jinja_json_checker import check
from jinja_json_checker.report import format_html, format_text

ROOT = Path(__file__).resolve().parents[1]


def run(*args, stdin=""):
    return subprocess.run(
        [sys.executable, "-m", "jinja_json_checker", *args],
        input=stdin.encode("utf-8"), capture_output=True, cwd=str(ROOT))


class CliTest(unittest.TestCase):
    def test_check_ok(self):
        proc = run("check", stdin='{"a": {{ foo | tojson }}}')
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Ошибок не найдено", proc.stdout.decode("utf-8"))

    def test_check_error(self):
        proc = run("check", stdin='{\n  "a": 1\n  "b": 2\n}')
        out = proc.stdout.decode("utf-8")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("строка 2", out)
        self.assertIn("Пропущена запятая", out)

    def test_fix_round_trip(self):
        proc = run("fix", stdin="{“a”: 1}")
        self.assertEqual(proc.stdout.decode("utf-8"), '{"a": 1}')

    def test_service_fix_returns_text_unchanged_when_clean(self):
        text = '{"a": 1}\n'
        proc = run("service-fix", stdin=text)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.decode("utf-8"), text)

    def test_check_file_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.json"
            src.write_text('{"a": True}', encoding="utf-8")
            html_path = Path(tmp) / "report.html"
            proc = run("check", str(src), "--html", str(html_path))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("<mark", html_path.read_text(encoding="utf-8"))


class ReportTest(unittest.TestCase):
    def test_text_points_to_column(self):
        out = format_text(check('{"a": 1,}'))
        self.assertIn("колонка 8", out)
        self.assertIn("       ^", out)

    def test_html_escapes_and_highlights(self):
        page = format_html(check('{"a": "<b>", “b”: 1}'))
        self.assertIn("&lt;b&gt;", page)
        self.assertIn('<mark class="error">“</mark>', page)
        self.assertIn('href="#L1"', page)

    def test_html_ok(self):
        page = format_html(check('{"a": 1}'))
        self.assertIn('class="ok"', page)


if __name__ == "__main__":
    unittest.main()
