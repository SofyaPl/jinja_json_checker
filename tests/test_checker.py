import unittest

from jinja_json_checker import check, fix_text
from jinja_json_checker.report import line_col

TEMPLATE = """{
  "title": "example",
  "author": {{ author | tojson }},
  "config": {
    "enabled": true,
    "options": [
      {
        "key": "foo",
        "value": {{ foo | tojson }}
      },
      {
        "key": "bar",
        "value": {{bar|tojson}}
      }
    ]
  }
}
"""

SCHEMA = """{
 "type": "object",
 "required": ["foo"],
 "properties": {
  "foo": {"type": "string", "title": "foo", "description": "пример поля"},
  "bar": {"type": "array", "items": {"type": "string"}}
 },
 "additionalProperties": false
}
"""


def messages(result):
    return [i.message for i in result.issues]


def first_error(text, mode="auto"):
    result = check(text, mode)
    assert result.errors, "expected an error, got %r" % messages(result)
    issue = result.errors[0]
    return issue, line_col(result.text, issue.offset)


class ValidInputTest(unittest.TestCase):
    def test_template(self):
        result = check(TEMPLATE)
        self.assertEqual(result.mode, "json")
        self.assertEqual(result.issues, [])

    def test_plain_json_schema(self):
        result = check(SCHEMA)
        self.assertEqual(result.mode, "json")
        self.assertEqual(result.issues, [])

    def test_expression_inside_string(self):
        self.assertEqual(check('{"greeting": "Hi, {{ user.name }}!"}').issues, [])

    def test_expression_as_key(self):
        self.assertEqual(check('{ {{ key_name | tojson }}: 1 }').issues, [])

    def test_whitespace_control(self):
        self.assertEqual(check('{"a": {{- foo | tojson -}}}').issues, [])

    def test_comment(self):
        self.assertEqual(check('{# note #}\n{"a": 1}').issues, [])

    def test_if_else_value(self):
        text = '{"a": {% if foo %}1{% elif bar %}2{% else %}3{% endif %}, "b": 2}'
        self.assertEqual(check(text).issues, [])

    def test_optional_member(self):
        text = '{\n  "a": 1{% if foo %},\n  "b": 2{% endif %}\n}'
        self.assertEqual(check(text).issues, [])

    def test_loop_with_comma(self):
        text = ('[{% for x in items %}{"key": {{ x | tojson }}}'
                '{% if not loop.last %},{% endif %}{% endfor %}]')
        self.assertEqual(check(text).issues, [])

    def test_set_statement(self):
        text = '{% set d = {"a": {"b": 1}} %}{"a": {{ d | tojson }}}'
        self.assertEqual(check(text).issues, [])

    def test_raw_block(self):
        text = '{"a": "{% raw %}{{ not a tag }}{% endraw %}"}'
        self.assertEqual(check(text).issues, [])

    def test_crlf(self):
        self.assertEqual(check(TEMPLATE.replace("\n", "\r\n")).issues, [])


class JsonErrorTest(unittest.TestCase):
    def test_missing_comma(self):
        issue, (line, col) = first_error('{\n  "a": "foo"\n  "b": 1\n}')
        self.assertIn("Пропущена запятая", issue.message)
        self.assertEqual((line, col), (2, 12))

    def test_trailing_comma(self):
        issue, (line, _) = first_error('{\n  "a": [1, 2,]\n}')
        self.assertIn("Лишняя запятая", issue.message)
        self.assertEqual(line, 2)

    def test_trailing_comma_after_expression(self):
        issue, _ = first_error('{"a": {{ foo | tojson }},\n}')
        self.assertIn("Лишняя запятая", issue.message)

    def test_unclosed_object(self):
        issue, (line, col) = first_error('{\n  "a": {\n    "b": 1\n}')
        self.assertIn("Не закрыта «{» из строки 1", issue.message)
        self.assertEqual((line, col), (1, 1))

    def test_missing_closing_brace_between_items(self):
        issue, _ = first_error('[\n  {"a": 1\n  {"a": 2}\n]')
        self.assertIn("не закрыт", issue.message)

    def test_wrong_bracket(self):
        issue, _ = first_error('{"a": [1, 2}')
        self.assertIn("Ожидалась «]»", issue.message)

    def test_single_quotes(self):
        issue, _ = first_error("{'a': 1}")
        self.assertIn("двойных кавычках", issue.message)

    def test_unquoted_key(self):
        issue, _ = first_error('{foo: 1}')
        self.assertIn('"foo"', issue.message)

    def test_python_literal(self):
        issue, _ = first_error('{"a": True}')
        self.assertIn("true", issue.message)

    def test_unclosed_string(self):
        issue, (line, _) = first_error('{\n  "a": "foo,\n  "b": 1\n}')
        self.assertIn("Строка не закрыта", issue.message)
        self.assertEqual(line, 2)

    def test_comment_not_allowed(self):
        issue, _ = first_error('{"a": 1 // note\n}')
        self.assertIn("Комментарии", issue.message)

    def test_extra_text(self):
        issue, _ = first_error('{"a": 1}}')
        self.assertIn("Лишний текст", issue.message)

    def test_bad_escape(self):
        issue, _ = first_error(r'{"path": "C:\temp\new"}'.replace("\\t", "\\q"))
        self.assertIn("escape", issue.message)

    def test_leading_zero(self):
        issue, _ = first_error('{"a": 01}')
        self.assertIn("с 0", issue.message)

    def test_empty(self):
        issue, _ = first_error("   ", "json")
        self.assertIn("Пустой", issue.message)


class WarningTest(unittest.TestCase):
    def test_duplicate_key(self):
        result = check('{"a": 1, "b": 2, "a": 3}')
        self.assertTrue(result.ok)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn('"a" повторяется', result.warnings[0].message)

    def test_duplicate_item_key(self):
        result = check(TEMPLATE.replace('"key": "bar"', '"key": "foo"'))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn('"key": "foo" повторяется', result.warnings[0].message)
        self.assertEqual(line_col(result.text, result.warnings[0].offset)[0], 12)

    def test_same_key_in_different_objects_is_fine(self):
        self.assertEqual(check('[{"a": 1}, {"a": 2}]').issues, [])


class CharsTest(unittest.TestCase):
    def test_smart_quotes_reported_once_each(self):
        result = check('{“a”: 1}')
        self.assertEqual(len(result.errors), 2)
        self.assertTrue(all("Умная кавычка" in m for m in messages(result)))
        self.assertEqual([i.offset for i in result.errors], [1, 3])

    def test_errors_after_smart_quotes_are_found(self):
        result = check('{\n  “a”: 1,\n  "b": 2\n  "c": 3\n}')
        self.assertEqual(len(result.errors), 3)
        self.assertIn("Пропущена запятая", result.errors[-1].message)

    def test_smart_apostrophe_in_expression(self):
        result = check('{"a": {{ foo | default(‘x’) }}}')
        self.assertEqual(len(result.errors), 2)

    def test_nbsp_outside_string_is_error(self):
        result = check('{"a":\u00a01}')
        self.assertEqual(len(result.issues), 1, messages(result))
        self.assertEqual(result.issues[0].severity, "error")
        self.assertIn("Неразрывный пробел", result.issues[0].message)

    def test_nbsp_inside_string_is_warning(self):
        result = check('{"a": "foo\u00a0bar"}')
        self.assertTrue(result.ok)
        self.assertEqual(len(result.warnings), 1)

    def test_guillemets_inside_string_are_fine(self):
        self.assertEqual(check('{"a": "статус «готово»"}').issues, [])

    def test_fix_text(self):
        fixed, count = fix_text('{“a”: ‘b’,\u00a0"c": 1\u200b}')
        self.assertEqual(fixed, '{"a": \'b\', "c": 1}')
        self.assertEqual(count, 6)

    def test_fix_keeps_guillemets(self):
        self.assertEqual(fix_text("«x»"), ("«x»", 0))

    def test_fixed_template_is_valid(self):
        broken = TEMPLATE.replace('"key": "foo"', '“key”: “foo”')
        self.assertFalse(check(broken).ok)
        self.assertEqual(check(fix_text(broken)[0]).issues, [])


class JinjaErrorTest(unittest.TestCase):
    def test_unclosed_expression(self):
        issue, (line, col) = first_error('{\n  "a": {{ foo | tojson,\n  "b": {{ bar }}\n}')
        self.assertIn("не закрыт", issue.message)
        self.assertEqual((line, col), (2, 8))

    def test_expression_closed_with_single_brace(self):
        result = check('{"a": {{ foo | tojson },\n "b": {{ bar }}}')
        self.assertEqual(len(result.errors), 1)
        self.assertIn("одной «}»", result.errors[0].message)

    def test_wrong_closer(self):
        issue, _ = first_error('{"a": {{ foo %}}')
        self.assertIn("закрыт «%}»", issue.message)

    def test_unclosed_paren(self):
        issue, _ = first_error('{"a": {{ foo | default("x" }}}')
        self.assertIn("скобка «(»", issue.message)

    def test_empty_filter(self):
        issue, _ = first_error('{"a": {{ foo | }}}')
        self.assertIn("фильтр", issue.message)

    def test_empty_expression(self):
        issue, _ = first_error('{"a": {{ }}}')
        self.assertIn("Пустое", issue.message)

    def test_unclosed_if(self):
        issue, _ = first_error('{"a": {% if foo %}1}')
        self.assertIn("Не закрыт «{% if %}»", issue.message)

    def test_extra_endif(self):
        issue, _ = first_error('{"a": 1{% endif %}}')
        self.assertIn("Лишний «{% endif %}»", issue.message)

    def test_crossed_blocks(self):
        issue, _ = first_error('{% for x in y %}{% if x %}{% endfor %}')
        self.assertIn("перед «{% endfor %}»", issue.message)

    def test_else_without_if(self):
        issue, _ = first_error('{"a": 1{% else %}}')
        self.assertIn("без открывающего", issue.message)

    def test_unknown_tag_is_warning(self):
        result = check('{"a": {% iff foo %}1{% endif %}}')
        self.assertTrue(any("опечатка" in i.message for i in result.warnings))

    def test_json_skipped_after_template_error(self):
        result = check('{"a": {{ foo, "b" 1}')
        self.assertTrue(any(i.severity == "info" for i in result.issues))
        self.assertTrue(all(i.source == "jinja" for i in result.errors))

    def test_unclosed_comment(self):
        issue, _ = first_error('{# note\n{"a": 1}')
        self.assertIn("Комментарий", issue.message)


class NoticeTest(unittest.TestCase):
    def notices(self, text):
        return [i.message for i in check(text).issues if i.severity == "info"]

    def test_json_stop_is_announced(self):
        self.assertTrue(any("остановилась" in m for m in self.notices('{"a": 1 "b": 2}')))

    def test_no_stop_notice_when_only_bad_chars(self):
        self.assertEqual(self.notices('{“a”: 1}'), [])

    def test_template_error_blocks_json(self):
        self.assertTrue(any("ещё не проверен" in m for m in self.notices('{"a": {{ foo }, "b" 1}')))


class ModeTest(unittest.TestCase):
    def test_plain_text(self):
        result = check("def f(x):\n    return x\n")
        self.assertEqual(result.mode, "text")
        self.assertEqual(result.errors, [])

    def test_plain_text_template(self):
        result = check("Hello, {{ user.name }}!")
        self.assertEqual(result.mode, "template")
        self.assertEqual(result.issues, [])

    def test_template_starting_with_tag(self):
        self.assertEqual(check('{% set x = 1 %}\n{"a": {{ x }}}').mode, "json")


if __name__ == "__main__":
    unittest.main()
