/*
 * JavaScript port of the jinja_json_checker Python package (chars, template,
 * jsonparse, checker). Messages and offsets must stay identical to the Python
 * version: tests/test_parity.py compares both on the same inputs.
 *
 * Works in the browser (sets globalThis.JJC) and in Node (module.exports).
 */
(function (root) {
  'use strict';

  const FIX_SUFFIX = '. Исправит «Починить кавычки»';
  let fixSuffix = FIX_SUFFIX;

  // char -> [replacement, human-readable name]
  const SMART_QUOTES = {
    '\u201c': ['"', 'умная кавычка “'],
    '\u201d': ['"', 'умная кавычка ”'],
    '\u201e': ['"', 'нижняя кавычка „'],
    '\u201f': ['"', 'кавычка ‟'],
    '\u2033': ['"', 'знак ″ вместо кавычки'],
    '\u2018': ["'", 'умный апостроф ‘'],
    '\u2019': ["'", 'умный апостроф ’'],
    '\u201a': ["'", 'нижний апостроф ‚'],
    '\u201b': ["'", 'апостроф ‛'],
    '\u2032': ["'", 'знак ′ вместо апострофа'],
  };

  const INVISIBLE = {
    '\u00a0': [' ', 'неразрывный пробел'],
    '\u202f': [' ', 'узкий неразрывный пробел'],
    '\u2007': [' ', 'цифровой пробел'],
    '\u2009': [' ', 'тонкий пробел'],
    '\u200a': [' ', 'волосяной пробел'],
    '\u200b': ['', 'пробел нулевой ширины'],
    '\u200c': ['', 'невидимый разделитель'],
    '\u200d': ['', 'невидимый соединитель'],
    '\u2060': ['', 'невидимый соединитель слов'],
    '\ufeff': ['', 'невидимая метка BOM'],
    '\u2028': ['\n', 'разделитель строк Unicode'],
    '\u2029': ['\n', 'разделитель абзацев Unicode'],
  };

  const FIXABLE = Object.assign({}, SMART_QUOTES, INVISIBLE);
  const GUILLEMETS = { '\u00ab': '«', '\u00bb': '»' };
  const SEVERITY_ORDER = { info: 0, warning: 1, error: 2 };

  function has(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  function cap(s) {
    return s.slice(0, 1).toUpperCase() + s.slice(1);
  }

  function hex4(n) {
    return n.toString(16).toUpperCase().padStart(4, '0');
  }

  function describe(ch) {
    return has(FIXABLE, ch) ? FIXABLE[ch][1] : 'символ U+' + hex4(ch.codePointAt(0));
  }

  function makeIssue(severity, message, offset, length, source) {
    return {
      severity: severity,
      message: message,
      offset: offset,
      length: length === undefined ? 1 : length,
      source: source || '',
    };
  }

  function isSpace(ch) {
    return /\s/.test(ch);
  }

  // ---------------------------------------------------------------- chars

  function invisibleHint(ch) {
    if (fixSuffix) return fixSuffix;
    const replacement = INVISIBLE[ch][0];
    if (replacement === '') return ': невидимый символ, удалите его';
    if (replacement === '\n') return ': невидимый символ, замените на перенос строки';
    return ': невидимый символ, замените на обычный пробел';
  }

  function findChars(text) {
    const issues = [];
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (has(SMART_QUOTES, ch)) {
        const it = makeIssue('error', cap(SMART_QUOTES[ch][1]) + ' вместо обычной ' +
          SMART_QUOTES[ch][0] + fixSuffix, i, 1, 'chars');
        it.replace = SMART_QUOTES[ch][0];
        issues.push(it);
      } else if (has(INVISIBLE, ch)) {
        const it = makeIssue('warning', cap(INVISIBLE[ch][1]) + invisibleHint(ch), i, 1, 'chars');
        it.replace = INVISIBLE[ch][0];
        issues.push(it);
      }
    }
    return issues;
  }

  function neutralize(text) {
    let out = '';
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (has(FIXABLE, ch)) {
        const r = FIXABLE[ch][0];
        out += r.length === 1 && r !== '\n' ? r : ' ';
      } else {
        out += ch;
      }
    }
    return out;
  }

  // ------------------------------------------------------------- template

  const NAME_RE = /^\s*([A-Za-z_][\p{L}\p{N}_]*)/u;
  const ENDRAW_RE = /\{%[-+]?\s*endraw\s*[-+]?%\}/g;
  const CLOSERS = { '{{': '}}', '{%': '%}' };
  const BRACKETS = { '(': ')', '[': ']', '{': '}' };
  const BLOCKS = new Set(['if', 'for', 'macro', 'call', 'filter', 'block', 'with',
    'autoescape', 'trans', 'set']);
  const MIDDLE = { elif: ['if'], else: ['if', 'for'], pluralize: ['trans'] };
  const STANDALONE = new Set(['extends', 'include', 'import', 'from', 'do', 'break',
    'continue', 'raw', 'endraw']);

  function jerr(message, offset, length, severity) {
    return makeIssue(severity || 'error', message, offset, length === undefined ? 2 : length, 'jinja');
  }

  function stripWsControl(body) {
    if (body.length && '-+'.includes(body[0])) body = body.slice(1);
    if (body.length && '-+'.includes(body[body.length - 1])) body = body.slice(0, -1);
    return body;
  }

  function tagOf(opener, start, end) {
    return { kind: opener === '{{' ? 'expr' : 'stmt', start: start, end: end, body: '', name: '' };
  }

  function scanTag(text, start, issues) {
    const opener = text.slice(start, start + 2);
    const closer = CLOSERS[opener];
    const wrongCloser = closer === '}}' ? '%}' : '}}';
    const n = text.length;
    let pos = start + 2;
    let quote = null;
    const stack = [];

    while (pos < n) {
      const ch = text[pos];
      if (quote) {
        if (ch === '\\') { pos += 2; continue; }
        if (ch === quote) quote = null;
        pos += 1;
        continue;
      }

      const pair = text.slice(pos, pos + 2);
      if (pair === '{{' || pair === '{%' || pair === '{#') {
        issues.push(jerr('Тег «' + opener + '» не закрыт: перед «' + pair + '» нет «' + closer + '»', start));
        return [null, pos];
      }
      if (pair === '%}' || (pair === '}}' && !stack.length)) {
        if (pair !== closer) {
          issues.push(jerr('Тег открыт «' + opener + '», а закрыт «' + wrongCloser + '»',
            start, pos + 2 - start));
          return [tagOf(opener, start, pos + 2), pos + 2];
        }
        if (stack.length) {
          const top = stack[stack.length - 1];
          issues.push(jerr('Внутри тега не закрыта скобка «' + top[0] + '»', top[1], 1));
        }
        return [finishTag(text, start, pos + 2, issues), pos + 2];
      }

      if (ch === '"' || ch === "'") {
        quote = ch;
      } else if (has(BRACKETS, ch)) {
        stack.push([ch, pos]);
      } else if (ch === ')' || ch === ']' || ch === '}') {
        if (stack.length && BRACKETS[stack[stack.length - 1][0]] === ch) {
          stack.pop();
        } else if (pair === closer) {
          const top = stack[stack.length - 1];
          issues.push(jerr('Внутри тега не закрыта скобка «' + top[0] + '»', top[1], 1));
          return [tagOf(opener, start, pos + 2), pos + 2];
        } else if (ch === '}' && !stack.length) {
          issues.push(jerr('Тег «' + opener + '» закрыт одной «}», а нужно «' + closer + '»',
            start, pos + 1 - start));
          return [tagOf(opener, start, pos + 1), pos + 1];
        } else {
          issues.push(jerr('Лишняя скобка «' + ch + '» внутри тега', pos, 1));
        }
      }
      pos += 1;
    }

    if (quote) {
      issues.push(jerr('Тег «' + opener + '» не закрыт: внутри не закрыта кавычка ' + quote, start));
    } else {
      issues.push(jerr('Тег «' + opener + '» не закрыт: нет «' + closer + '»', start));
    }
    return [null, n];
  }

  function finishTag(text, start, end, issues) {
    const opener = text.slice(start, start + 2);
    const body = stripWsControl(text.slice(start + 2, end - 2));
    if (opener === '{{') {
      const stripped = body.trim();
      if (!stripped) {
        issues.push(jerr('Пустое выражение «{{ }}»', start, end - start));
      } else if (stripped.endsWith('|')) {
        issues.push(jerr('После «|» не указан фильтр', start, end - start));
      } else if (stripped.startsWith('|')) {
        issues.push(jerr('Перед «|» нет значения', start, end - start));
      }
      return { kind: 'expr', start: start, end: end, body: body, name: '' };
    }
    const m = NAME_RE.exec(body);
    const name = m ? m[1] : '';
    if (!name) {
      issues.push(jerr('Пустой или неправильный тег «{% %}»', start, end - start));
    }
    return { kind: 'stmt', start: start, end: end, body: body, name: name };
  }

  function scanTags(text) {
    const tags = [];
    const issues = [];
    const opener = /\{[{%#]/g;
    let pos = 0;
    for (;;) {
      opener.lastIndex = pos;
      const m = opener.exec(text);
      if (!m) break;
      const start = m.index;
      if (m[0] === '{#') {
        const close = text.indexOf('#}', start + 2);
        if (close < 0) {
          issues.push(jerr('Комментарий «{#» не закрыт: нет «#}»', start));
          break;
        }
        tags.push({ kind: 'comment', start: start, end: close + 2, body: '', name: '' });
        pos = close + 2;
        continue;
      }

      const res = scanTag(text, start, issues);
      const tag = res[0];
      pos = res[1];
      if (tag === null) continue;
      tags.push(tag);
      if (tag.kind === 'stmt' && tag.name === 'raw') {
        ENDRAW_RE.lastIndex = tag.end;
        const endM = ENDRAW_RE.exec(text);
        if (!endM) {
          issues.push(jerr('«{% raw %}» не закрыт: нет «{% endraw %}»', tag.start, tag.end - tag.start));
          break;
        }
        tags.push({ kind: 'stmt', start: endM.index, end: endM.index + endM[0].length,
          body: 'endraw', name: 'endraw' });
        pos = endM.index + endM[0].length;
      }
    }
    return [tags, issues];
  }

  function isBlockSet(body) {
    let depth = 0;
    let quote = null;
    for (const ch of body) {
      if (quote) {
        if (ch === quote) quote = null;
      } else if (ch === '"' || ch === "'") {
        quote = ch;
      } else if ('([{'.includes(ch)) {
        depth += 1;
      } else if (')]}'.includes(ch)) {
        depth -= 1;
      } else if (ch === '=' && depth === 0) {
        return false;
      }
    }
    return true;
  }

  function label(name) {
    return '{% ' + name + ' %}';
  }

  function matchBlocks(tags) {
    const issues = [];
    const removed = [];
    const conditional = [];
    const stack = [];

    function close(frame, endTag) {
      if (frame.inElse) removed.push([frame.last.end, endTag.start]);
      const firstEnd = frame.firstBranchEnd !== null ? frame.firstBranchEnd : endTag.start;
      if (frame.name === 'if' || frame.name === 'for') conditional.push([frame.tag.end, firstEnd]);
    }

    for (const tag of tags) {
      if (tag.kind !== 'stmt' || !tag.name) continue;
      const name = tag.name;
      const size = tag.end - tag.start;

      if (BLOCKS.has(name) && (name !== 'set' || isBlockSet(tag.body.replace(NAME_RE, '')))) {
        stack.push({ name: name, tag: tag, last: tag, inElse: false, seenElse: false,
          firstBranchEnd: null });
      } else if (has(MIDDLE, name)) {
        const frame = stack[stack.length - 1];
        if (frame && MIDDLE[name].includes(frame.name)) {
          if (frame.seenElse) {
            issues.push(jerr('«' + label(name) + '» после «{% else %}»', tag.start, size));
          }
          if (frame.inElse) removed.push([frame.last.end, tag.start]);
          if (frame.firstBranchEnd === null) frame.firstBranchEnd = tag.start;
          frame.last = tag;
          frame.inElse = true;
          frame.seenElse = frame.seenElse || name === 'else';
        } else {
          const parents = MIDDLE[name].slice().sort().map(function (p) {
            return '«' + label(p) + '»';
          }).join(' или ');
          issues.push(jerr('«' + label(name) + '» без открывающего ' + parents, tag.start, size));
        }
      } else if (name.startsWith('end') && BLOCKS.has(name.slice(3))) {
        const opener = name.slice(3);
        let idx = -1;
        for (let k = stack.length - 1; k >= 0; k--) {
          if (stack[k].name === opener) { idx = k; break; }
        }
        if (idx < 0) {
          issues.push(jerr('Лишний «' + label(name) + '»: нет открывающего «' + label(opener) + '»',
            tag.start, size));
          continue;
        }
        for (const frame of stack.slice(idx + 1)) {
          issues.push(jerr('Не закрыт «' + label(frame.name) + '»: перед «' + label(name) +
            '» нужен «' + label('end' + frame.name) + '»', frame.tag.start, frame.tag.end - frame.tag.start));
        }
        close(stack[idx], tag);
        stack.length = idx;
      } else if (STANDALONE.has(name) || BLOCKS.has(name)) {
        // nothing to match
      } else {
        issues.push(jerr('Неизвестный тег «' + label(name) + '» — возможно, опечатка',
          tag.start, size, 'warning'));
      }
    }

    for (const frame of stack) {
      issues.push(jerr('Не закрыт «' + label(frame.name) + '»: нет «' + label('end' + frame.name) + '»',
        frame.tag.start, frame.tag.end - frame.tag.start));
    }
    return [issues, removed, conditional];
  }

  function jsonStringState(chars) {
    const state = new Array(chars.length).fill(false);
    let inStr = false;
    let escaped = false;
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      state[i] = inStr;
      if (inStr) {
        if (escaped) escaped = false;
        else if (ch === '\\') escaped = true;
        else if (ch === '"' || ch === '\n') inStr = false;
      } else if (ch === '"') {
        inStr = true;
      }
    }
    return state;
  }

  function analyze(text) {
    const scanned = scanTags(text);
    const tags = scanned[0];
    const issues = scanned[1];
    const matched = matchBlocks(tags);
    issues.push.apply(issues, matched[0]);
    const removed = matched[1];
    const condRegions = matched[2];

    const n = text.length;
    const chars = text.split('');
    const dropped = new Array(n).fill(false);

    function blank(a, b, drop) {
      for (let k = a; k < b; k++) {
        if (chars[k] !== '\n') chars[k] = ' ';
        if (drop) dropped[k] = true;
      }
    }

    for (const tag of tags) blank(tag.start, tag.end, false);
    for (const r of removed) blank(r[0], r[1], true);

    const conditional = new Array(n).fill(false);
    for (const r of condRegions) {
      for (let k = r[0]; k < r[1]; k++) conditional[k] = true;
    }

    const inStr = jsonStringState(chars);
    const groups = [];
    for (const tag of tags) {
      if (tag.kind !== 'expr' || dropped[tag.start]) continue;
      const last = groups[groups.length - 1];
      if (last && !chars.slice(last[1], tag.start).join('').trim()) {
        last[1] = tag.end;
      } else {
        groups.push([tag.start, tag.end]);
      }
    }
    for (const g of groups) {
      const start = g[0];
      if (inStr[start]) continue;
      let nxt = g[1];
      while (nxt < n && isSpace(chars[nxt])) nxt += 1;
      if (nxt < n && chars[nxt] === ':') {
        chars[start] = '"';
        chars[start + 1] = '"';
      } else {
        chars[start] = '0';
      }
    }

    return {
      hasTemplate: tags.length > 0 || issues.length > 0,
      tags: tags,
      issues: issues,
      masked: chars.join(''),
      conditional: conditional,
    };
  }

  // ------------------------------------------------------------ jsonparse

  const NUMBER_RE = /-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;
  const WORD_RE = /[A-Za-z_\u0400-\u04FF][\p{L}\p{N}_\u0400-\u04FF]*/uy;
  const DIGITS = '0123456789';
  const WHITESPACE = ' \t\n\r';
  const ESCAPES = '"\\/bfnrtu';
  const PYTHON_LITERALS = { True: 'true', False: 'false', None: 'null' };
  const CLOSING = { '{': '}', '[': ']' };
  const IDENTITY_FIELDS = ['key', 'name', 'id'];
  const STOP = {};

  function matchAt(re, text, i) {
    re.lastIndex = i;
    return re.exec(text);
  }

  function isAlnum(ch) {
    return /[\p{L}\p{N}]/u.test(ch);
  }

  function Parser(text, conditional) {
    this.text = text;
    this.n = text.length;
    this.cond = conditional && conditional.length ? conditional : new Array(this.n).fill(false);
    this.i = 0;
    this.issues = [];
    this.open = [];
    this.lineStarts = [0];
    for (let k = 0; k < text.length; k++) {
      if (text[k] === '\n') this.lineStarts.push(k + 1);
    }
  }

  Parser.prototype.line = function (offset) {
    let lo = 0;
    let hi = this.lineStarts.length;
    while (lo + 1 < hi) {
      const mid = (lo + hi) >> 1;
      if (this.lineStarts[mid] <= offset) lo = mid;
      else hi = mid;
    }
    return lo + 1;
  };

  Parser.prototype.error = function (message, offset, length) {
    this.issues.push(makeIssue('error', message, offset, length === undefined ? 1 : length, 'json'));
    throw STOP;
  };

  Parser.prototype.warning = function (message, offset, length) {
    this.issues.push(makeIssue('warning', message, offset, length === undefined ? 1 : length, 'json'));
  };

  Parser.prototype.peek = function () {
    return this.i < this.n ? this.text[this.i] : '';
  };

  Parser.prototype.skipWs = function () {
    while (this.i < this.n) {
      const ch = this.text[this.i];
      if (WHITESPACE.includes(ch)) {
        this.i += 1;
      } else if (this.text.startsWith('//', this.i) || this.text.startsWith('/*', this.i)) {
        this.error('Комментарии в JSON не допускаются', this.i, 2);
      } else {
        break;
      }
    }
  };

  Parser.prototype.unclosed = function () {
    const top = this.open[this.open.length - 1];
    this.error('Не закрыта «' + top[0] + '» из строки ' + this.line(top[1]) + ': нет «' +
      CLOSING[top[0]] + '»', top[1]);
  };

  Parser.prototype.unexpected = function (expected) {
    const i = this.i;
    const ch = this.peek();
    if (!ch) {
      if (this.open.length) this.unclosed();
      this.error('Текст закончился, а ожидалось ' + expected, Math.max(this.n - 1, 0));
    }
    if (has(SMART_QUOTES, ch)) {
      this.error(cap(describe(ch)) + ' вместо обычной ' + SMART_QUOTES[ch][0] + fixSuffix, i);
    }
    if (has(GUILLEMETS, ch)) this.error('Кавычка-ёлочка ' + ch + ' вместо обычной "', i);
    if (ch === "'") {
      this.error('В JSON строки и ключи пишутся в двойных кавычках ", а не в одинарных \'', i);
    }
    if (has(INVISIBLE, ch)) {
      this.error(cap(describe(ch)) + ': невидимый символ, JSON его не принимает' + fixSuffix, i);
    }
    if (ch === ',') this.error('Лишняя запятая', i);
    const m = matchAt(WORD_RE, this.text, i);
    if (m) {
      const word = m[0];
      if (has(PYTHON_LITERALS, word)) {
        this.error('В JSON пишется ' + PYTHON_LITERALS[word] + ', а не ' + word, i, word.length);
      }
      if (expected === 'ключ') {
        this.error('Ключ должен быть в двойных кавычках: "' + word + '"', i, word.length);
      }
      this.error('Непонятное слово «' + word + '»: строки в JSON берутся в двойные кавычки', i, word.length);
    }
    this.error('Неожиданный символ «' + ch + '», ожидалось ' + expected, i);
  };

  Parser.prototype.missingCommaOk = function (prevEnd) {
    return this.cond[this.i] || (prevEnd > 0 && this.cond[prevEnd - 1]);
  };

  Parser.prototype.parse = function () {
    this.skipWs();
    if (this.i >= this.n) this.error('Пустой текст: нечего проверять', 0);
    this.value();
    this.skipWs();
    if (this.i < this.n) {
      const ch = this.peek();
      let hint = '';
      if (ch === ']' || ch === '}') hint = ': лишняя закрывающая скобка «' + ch + '»';
      else if (ch === '{' || ch === '[') hint = ': похоже, JSON вставлен дважды или потеряна запятая';
      this.error('Лишний текст после конца JSON' + hint, this.i);
    }
  };

  Parser.prototype.value = function () {
    this.skipWs();
    const ch = this.peek();
    if (ch === '{') return this.obj();
    if (ch === '[') {
      this.arr();
    } else if (ch === '"') {
      return this.string();
    } else if (ch && ('-' + DIGITS).includes(ch)) {
      this.number();
    } else if (ch && 'tfn'.includes(ch) && matchAt(WORD_RE, this.text, this.i)) {
      this.literal();
    } else {
      this.unexpected('значение');
    }
    return null;
  };

  Parser.prototype.obj = function () {
    this.open.push(['{', this.i]);
    this.i += 1;
    const keys = new Map();
    const members = new Map();
    this.skipWs();
    if (this.peek() === '}') {
      this.i += 1;
      this.open.pop();
      return members;
    }
    for (;;) {
      this.skipWs();
      if (this.peek() !== '"') this.unexpected('ключ');
      const keyPos = this.i;
      const key = this.string();
      if (keys.has(key)) {
        this.warning('Ключ "' + key + '" повторяется (первый раз — в строке ' +
          this.line(keys.get(key)) + ')', keyPos, this.i - keyPos);
      } else {
        keys.set(key, keyPos);
      }
      this.skipWs();
      if (this.peek() !== ':') {
        if (!this.peek()) this.unclosed();
        this.error('После ключа "' + key + '" нужно двоеточие «:»', this.i);
      }
      this.i += 1;
      this.skipWs();
      const valuePos = this.i;
      members.set(key, [this.value(), valuePos]);
      if (this.afterItem('}', keyPos)) return members;
    }
  };

  Parser.prototype.arr = function () {
    this.open.push(['[', this.i]);
    this.i += 1;
    const seen = new Map();
    this.skipWs();
    if (this.peek() === ']') {
      this.i += 1;
      this.open.pop();
      return;
    }
    for (;;) {
      this.skipWs();
      const itemPos = this.i;
      const item = this.value();
      if (item instanceof Map) this.checkIdentity(item, seen);
      if (this.afterItem(']', itemPos)) return;
    }
  };

  Parser.prototype.checkIdentity = function (item, seen) {
    for (const field of IDENTITY_FIELDS) {
      const entry = item.get(field);
      if (!entry || typeof entry[0] !== 'string') continue;
      const value = entry[0];
      const pos = entry[1];
      const id = field + '\u0000' + value;
      if (!seen.has(id)) {
        seen.set(id, pos);
      } else {
        const length = this.text.indexOf('"', pos + 1) + 1 - pos;
        this.warning('Элемент с "' + field + '": "' + value + '" повторяется в списке (первый раз — в строке ' +
          this.line(seen.get(id)) + ')', pos, Math.max(length, 1));
      }
    }
  };

  Parser.prototype.afterItem = function (close, itemPos) {
    const prevEnd = this.i;
    this.skipWs();
    const ch = this.peek();
    if (ch === ',') {
      const comma = this.i;
      this.i += 1;
      this.skipWs();
      if (this.peek() === close) {
        if (!this.cond[comma]) this.error('Лишняя запятая перед «' + close + '»', comma);
        this.i += 1;
        this.open.pop();
        return true;
      }
      return false;
    }
    if (ch === close) {
      this.i += 1;
      this.open.pop();
      return true;
    }
    if (!ch) this.unclosed();
    if (ch === ']' || ch === '}') {
      const top = this.open[this.open.length - 1];
      this.error('Ожидалась «' + close + '» (закрывает «' + top[0] + '» из строки ' + this.line(top[1]) +
        '), а стоит «' + ch + '»', this.i);
    }
    if ('"{[-0123456789tfn'.includes(ch) && this.missingCommaOk(prevEnd)) return false;
    if (close === '}' && (ch === '{' || ch === '[')) {
      const top = this.open[this.open.length - 1];
      this.error('Здесь начинается новый ' + (ch === '{' ? 'объект' : 'список') + ', а объект «{» из строки ' +
        this.line(top[1]) + ' не закрыт: пропущена «}» или запятая', this.i);
    }
    if (('"{[' + DIGITS).includes(ch)) this.error('Пропущена запятая после этого значения', prevEnd - 1);
    this.unexpected('запятая или «' + close + '»');
    return false;
  };

  Parser.prototype.string = function () {
    const start = this.i;
    this.i += 1;
    let out = '';
    for (;;) {
      if (this.i >= this.n) this.error('Строка не закрыта кавычкой "', start);
      const ch = this.text[this.i];
      if (ch === '"') {
        this.i += 1;
        return out;
      }
      if (ch === '\n') {
        let smart = null;
        for (let k = start; k < this.i; k++) {
          if (has(SMART_QUOTES, this.text[k])) { smart = this.text[k]; break; }
        }
        const hint = smart
          ? ': внутри есть ' + describe(smart) + ', возможно, она должна была закрыть строку'
          : ': пропущена закрывающая кавычка "?';
        this.error('Строка не закрыта до конца строки' + hint, start);
      }
      if (ch === '\t') {
        this.error('Табуляция внутри строки недопустима в JSON: замените на пробел или \\t', this.i);
      }
      if (ch.charCodeAt(0) < 0x20) {
        this.error('Управляющий символ U+' + hex4(ch.charCodeAt(0)) + ' внутри строки', this.i);
      }
      if (ch === '\\') {
        const nxt = this.text.slice(this.i + 1, this.i + 2);
        if (!nxt || !ESCAPES.includes(nxt)) {
          this.error('Неправильная escape-последовательность «\\' + nxt + '»: обратный слэш ' +
            'в JSON пишется как \\\\', this.i, 2);
        }
        if (nxt === 'u') {
          const hexpart = this.text.slice(this.i + 2, this.i + 6);
          if (!/^[0-9a-fA-F]{4}$/.test(hexpart)) {
            this.error('После \\u нужны 4 шестнадцатеричные цифры', this.i, 2);
          }
          out += String.fromCharCode(parseInt(hexpart, 16));
          this.i += 6;
          continue;
        }
        out += nxt;
        this.i += 2;
        continue;
      }
      out += ch;
      this.i += 1;
    }
  };

  Parser.prototype.number = function () {
    const m = matchAt(NUMBER_RE, this.text, this.i);
    if (!m) this.error('Неправильное число', this.i);
    const end = this.i + m[0].length;
    if (end < this.n && (isAlnum(this.text[end]) || '._'.includes(this.text[end]))) {
      if (this.text.slice(this.i, end).replace(/^-+/, '') === '0' && DIGITS.includes(this.text[end])) {
        this.error('Число не может начинаться с 0', this.i, end - this.i + 1);
      }
      this.error('Неправильное число', this.i, end - this.i + 1);
    }
    this.i = end;
  };

  Parser.prototype.literal = function () {
    const m = matchAt(WORD_RE, this.text, this.i);
    const word = m ? m[0] : '';
    if (word === 'true' || word === 'false' || word === 'null') this.i += word.length;
    else this.unexpected('значение');
  };

  function parseJson(text, conditional) {
    const p = new Parser(text, conditional);
    try {
      p.parse();
    } catch (e) {
      if (e !== STOP) throw e;
    }
    return p.issues;
  }

  // -------------------------------------------------------------- checker

  const JSON_BLOCKED = 'JSON ещё не проверен: сначала исправьте ошибки в тегах шаблона. ' +
    'После этого могут найтись новые ошибки';
  const JSON_STOPPED = 'Проверка JSON остановилась на первой ошибке. ' +
    'После её исправления могут найтись следующие';
  const NOT_JSON = 'Это не похоже на JSON или шаблон: проверены только кавычки и невидимые символы';

  function detectMode(text, masked) {
    const head = masked.replace(/^\s+/, '').slice(0, 1);
    if (head === '{' || head === '[') return 'json';
    if (masked !== text) return 'template';
    return 'text';
  }

  function checkJson(analysis, charOffsets) {
    const found = parseJson(analysis.masked, analysis.conditional);
    const error = found.find(function (i) { return i.severity === 'error'; });
    if (!error || !charOffsets.has(error.offset)) return found;
    return [error].concat(parseJson(neutralize(analysis.masked), analysis.conditional));
  }

  /**
   * options.mode: "auto" | "json" | "template"
   * options.fixHint: mention the "Починить кавычки" command in messages (default true)
   */
  function check(text, options) {
    options = options || {};
    fixSuffix = options.fixHint === false ? '' : FIX_SUFFIX;
    text = text.replace(/\r\n/g, '\n');
    let mode = options.mode || 'auto';

    const analysis = analyze(text);
    if (mode === 'auto') mode = detectMode(text, analysis.masked);

    let issues = findChars(text);
    issues.push.apply(issues, analysis.issues);
    const jinjaErrors = analysis.issues.some(function (i) { return i.severity === 'error'; });

    if (mode === 'json') {
      if (jinjaErrors) {
        issues.push(makeIssue('info', JSON_BLOCKED, 0, 0, 'json'));
      } else {
        const charOffsets = new Set(issues.filter(function (i) { return i.source === 'chars'; })
          .map(function (i) { return i.offset; }));
        const found = checkJson(analysis, charOffsets);
        issues.push.apply(issues, found);
        if (found.some(function (i) { return i.severity === 'error' && !charOffsets.has(i.offset); })) {
          issues.push(makeIssue('info', JSON_STOPPED, 0, 0, 'json'));
        }
      }
    } else if (mode === 'text') {
      issues.push(makeIssue('info', NOT_JSON, 0, 0, 'text'));
    }

    const charIssues = new Map();
    for (const i of issues) if (i.source === 'chars') charIssues.set(i.offset, i);
    const deduped = [];
    for (const it of issues) {
      const twin = charIssues.get(it.offset);
      if (twin && it.source === 'json' && it.severity !== 'info') {
        if (twin.severity === 'error') continue;
        twin.severity = it.severity;
        twin.message = it.message;
        continue;
      }
      deduped.push(it);
    }

    deduped.sort(function (a, b) {
      const ai = a.severity === 'info' ? 1 : 0;
      const bi = b.severity === 'info' ? 1 : 0;
      if (ai !== bi) return ai - bi;
      if (a.offset !== b.offset) return a.offset - b.offset;
      return SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity];
    });

    const result = {
      mode: mode,
      text: text,
      issues: deduped,
      errors: deduped.filter(function (i) { return i.severity === 'error'; }),
      warnings: deduped.filter(function (i) { return i.severity === 'warning'; }),
    };
    result.ok = result.errors.length === 0;
    return result;
  }

  function lineCol(text, offset) {
    let line = 1;
    let lineStart = 0;
    for (let k = 0; k < offset && k < text.length; k++) {
      if (text[k] === '\n') { line += 1; lineStart = k + 1; }
    }
    return [line, offset - lineStart + 1];
  }

  const api = {
    check: check,
    lineCol: lineCol,
    describe: describe,
    SMART_QUOTES: SMART_QUOTES,
    INVISIBLE: INVISIBLE,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.JJC = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
