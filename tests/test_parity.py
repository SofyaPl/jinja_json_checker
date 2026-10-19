"""The browser extension uses a JavaScript port of the checker. Make sure both agree."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja_json_checker import check

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "run_checker.js"

BASES = [
    """{
  "title": "example",
  "author": {{ author | tojson }},
  "config": {
    "enabled": true,
    "options": [
      {"key": "foo", "value": {{ foo | tojson }}},
      {"key": "bar", "value": {{bar|tojson}}}
    ]
  }
}""",
    """{
 "type": "object",
 "required": ["foo"],
 "properties": {
  "foo": {"type": "string", "description": "пример \\"поля\\" \\u0041"},
  "n": {"type": "number", "default": -1.5e3}
 },
 "additionalProperties": false
}""",
    """[{% for x in items %}{"name": {{ x | tojson }}}{% if not loop.last %},{% endif %}{% endfor %}]""",
    """{"a": {% if foo %}1{% elif bar %}2{% else %}3{% endif %}, {# note #} "b": null}""",
    """{% set d = {"a": {"b": 1}} %}{"x": "{% raw %}{{ y }}{% endraw %}", "d": {{ d | tojson }}}""",
    """{"t": {{ title | default("x") | tojson }}, "f": {{ 1 if a.b is defined else -2.5 }}}""",
    """  "k": [1, 2],\n  "m": {{ m }}\n""",
]

INSERTS = [",", '"', "'", "{", "}", "[", "]", ":", "“", "”", "\u00a0", "\u200b", "%", "#",
           "}}", "{{", "{%", "%}", "True", "\\", "\n", "\t", "0", "-", "/"]


def generate():
    cases = list(BASES)
    for base in BASES:
        for pos in range(len(base)):
            cases.append(base[:pos] + base[pos + 1:])
            for ins in INSERTS[(pos % 5)::5]:
                cases.append(base[:pos] + ins + base[pos:])
    return cases


def py_result(text):
    r = check(text)
    return {"mode": r.mode,
            "issues": [[i.severity, i.message, i.offset, i.length, i.source] for i in r.issues]}


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ParityTest(unittest.TestCase):
    def test_both_versions_agree(self):
        cases = generate()
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "cases.json"
            src.write_text(json.dumps(cases), encoding="utf-8")
            out = subprocess.run(["node", str(RUNNER), str(src)], capture_output=True, check=True)
        js_results = json.loads(out.stdout.decode("utf-8"))
        self.assertEqual(len(js_results), len(cases))
        mismatches = []
        for text, js in zip(cases, js_results):
            py = py_result(text)
            if py != js:
                mismatches.append((text, py, js))
        if mismatches:
            text, py, js = mismatches[0]
            self.fail("%d of %d cases differ. First:\n%r\npy: %r\njs: %r"
                      % (len(mismatches), len(cases), text, py, js))

    def test_javascript_unit_tests(self):
        proc = subprocess.run(["node", "--test", str(ROOT / "tests" / "js" / "checker.test.js")],
                              capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
