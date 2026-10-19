const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const JJC = require(path.join(__dirname, '..', '..', 'extension', 'checker.js'));

test('extension messages do not mention the fix command', function () {
  const r = JJC.check('{“a”: 1,\u00a0"b": 2}', { fixHint: false });
  assert.ok(r.issues.length > 0);
  for (const i of r.issues) assert.ok(!i.message.includes('Починить'), i.message);
});

test('smart quotes and invisible characters carry the replacement', function () {
  const r = JJC.check('{“a”: "x\u200by"}', { fixHint: false });
  const replaces = r.issues.filter(function (i) { return i.replace !== undefined; })
    .map(function (i) { return i.replace; });
  assert.deepStrictEqual(replaces, ['"', '"', '']);
});

test('plain text is only checked for characters', function () {
  const r = JJC.check('hello world');
  assert.strictEqual(r.mode, 'text');
  assert.strictEqual(r.errors.length, 0);
});

test('windows line endings from the editor give the same positions', function () {
  const unix = JJC.check('{\n  "a": 1\n  "b": 2\n}');
  const win = JJC.check('{\r\n  "a": 1\r\n  "b": 2\r\n}');
  assert.deepStrictEqual(win.issues, unix.issues);
  assert.deepStrictEqual(JJC.lineCol(unix.text, unix.errors[0].offset), [2, 8]);
});
