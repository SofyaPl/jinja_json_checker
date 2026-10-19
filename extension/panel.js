// Side panel shown on top of the page. Read-only: it never changes the page.
(function () {
  'use strict';
  if (window.__jjcShow) return;

  const JJC = window.JJC;
  const SEVERITY_ORDER = { info: 0, warning: 1, error: 2 };
  const LEVEL_NAMES = ['info', 'warning', 'error'];
  const LABELS = { error: 'Ошибка', warning: 'Внимание', info: 'Заметка' };
  const MODE_NAMES = { json: 'JSON', template: 'шаблон Jinja2', text: 'текст' };

  const CSS = `
:host { all: initial; }
.panel { position: fixed; z-index: 2147483647; box-sizing: border-box;
  min-width: 320px; min-height: 200px; display: flex; flex-direction: column;
  overflow: hidden; resize: both;
  background: #fff; color: #1d1d1f; border: 1px solid #c8c8c8; border-radius: 8px;
  box-shadow: 0 6px 24px rgba(0,0,0,.18);
  font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
header { padding: 10px 12px 8px; border-bottom: 1px solid #e3e3e3; cursor: move;
  user-select: none; background: #f6f8fa; }
.top { display: flex; align-items: center; gap: 4px; }
.title { font-weight: 600; flex: 1; }
.close { border: 0; background: none; font-size: 18px; line-height: 1; cursor: pointer;
  color: #666; padding: 2px 6px; border-radius: 4px; }
.close:hover { background: #e3e3e3; color: #000; }
.summary { font-size: 15px; font-weight: 600; margin-top: 4px; }
.summary.ok { color: #1a7f37; } .summary.bad { color: #cf222e; } .summary.warn { color: #9a6700; }
.meta { color: #666; font-size: 12px; margin-top: 2px; }
.notice { margin-top: 6px; padding: 6px 8px; border-radius: 6px; font-weight: 600;
  background: #ffebe9; color: #cf222e; border: 1px solid #ff8182; cursor: auto; }
.notice.soft { background: #fff8c5; color: #7d4e00; border-color: #d4a72c; }
.issues { max-height: 38vh; overflow: auto; border-bottom: 1px solid #e3e3e3; }
.issue { padding: 6px 12px; border-top: 1px solid #f0f0f0; cursor: pointer; }
.issue:hover { background: #f6f8fa; }
.issue .where { color: #57606a; font-size: 12px; }
.tag { font-weight: 600; } .tag.error { color: #cf222e; } .tag.warning { color: #9a6700; }
.tag.info { color: #57606a; }
.swap { display: inline-flex; align-items: center; gap: 6px; margin-top: 3px; font-size: 12px; }
.chip { font: 14px Menlo, Consolas, monospace; padding: 0 6px; border-radius: 4px;
  border: 1px solid #d0d7de; background: #f6f8fa; min-width: 10px; text-align: center; }
.chip.bad { background: #ffebe9; border-color: #ff8182; }
.chip.good { background: #dafbe1; border-color: #4ac26b; }
.code { flex: 1; overflow: auto; background: #fafafa; }
pre { margin: 0; padding: 8px 0; font: 12px/1.5 Menlo, Consolas, monospace; tab-size: 4; }
.line { display: block; padding-right: 12px; white-space: pre; }
.ln { display: inline-block; width: 3.5em; padding-right: .8em; text-align: right;
  color: #999; user-select: none; }
.line.error { background: #ffebe9; } .line.warning { background: #fff8c5; }
.line.flash { outline: 2px solid #0969da; outline-offset: -2px; }
mark.error { background: #ff8182; color: #000; border-bottom: 2px solid #cf222e; }
mark.warning { background: #ffd33d; color: #000; }
.empty { padding: 16px 12px; color: #444; }
details { border-top: 1px solid #e3e3e3; padding: 8px 12px; }
summary { cursor: pointer; color: #0969da; }
textarea { width: 100%; box-sizing: border-box; height: 120px; margin-top: 6px;
  font: 12px Menlo, Consolas, monospace; }
.btn { margin-top: 6px; padding: 4px 12px; border: 1px solid #d0d7de; border-radius: 6px;
  background: #f6f8fa; cursor: pointer; font: inherit; }
.hint { color: #666; font-size: 12px; padding: 6px 12px; border-top: 1px solid #e3e3e3; }
`;

  let host = null;
  let root = null;
  let box = null;
  let saveTimer = null;

  function defaultBox() {
    return { left: 8, top: 8, width: 480, height: window.innerHeight - 16 };
  }

  function clampBox(b) {
    const w = Math.max(320, Math.min(b.width, window.innerWidth));
    const h = Math.max(200, Math.min(b.height, window.innerHeight));
    return {
      width: w,
      height: h,
      left: Math.max(0, Math.min(b.left, window.innerWidth - 80)),
      top: Math.max(0, Math.min(b.top, window.innerHeight - 40)),
    };
  }

  function applyBox(panel) {
    panel.style.left = box.left + 'px';
    panel.style.top = box.top + 'px';
    panel.style.width = box.width + 'px';
    panel.style.height = box.height + 'px';
  }

  function saveBox() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      try {
        chrome.storage.local.set({ panelBox: box });
      } catch (e) {
        // storage is optional: the position is still kept until the page reloads
      }
    }, 300);
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function plural(n, one, few, many) {
    if (n % 10 === 1 && n % 100 !== 11) return one;
    if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) return few;
    return many;
  }

  function summaryText(r) {
    const kind = MODE_NAMES[r.mode] || r.mode;
    const e = r.errors.length;
    const w = r.warnings.length;
    if (!e && !w) return 'Ошибок не найдено (' + kind + ')';
    const parts = [];
    if (e) parts.push(e + ' ' + plural(e, 'ошибка', 'ошибки', 'ошибок'));
    if (w) parts.push(w + ' ' + plural(w, 'предупреждение', 'предупреждения', 'предупреждений'));
    return kind.charAt(0).toUpperCase() + kind.slice(1) + ': ' + parts.join(', ');
  }

  function visibleChar(ch) {
    if (ch === '') return 'удалить';
    if (ch === ' ') return '␣';
    if (ch === '\n') return '↵';
    if (JJC.INVISIBLE[ch]) return '·';
    return ch;
  }

  function close() {
    if (host) host.remove();
    host = null;
    root = null;
    window.removeEventListener('keydown', onWindowKey, true);
  }

  // Esc closes the panel wherever the focus is; the page still receives the key.
  function onWindowKey(e) {
    if (e.key === 'Escape') close();
  }

  function ensureHost() {
    if (host && document.documentElement.contains(host)) return;
    host = document.createElement('jjc-panel');
    root = host.attachShadow({ mode: 'closed' });
    document.documentElement.appendChild(host);
    window.addEventListener('keydown', onWindowKey, true);
  }

  function render(data) {
    ensureHost();
    root.textContent = '';
    const style = el('style');
    style.textContent = CSS;
    root.appendChild(style);

    const panel = el('div', 'panel');
    panel.tabIndex = -1;
    if (!box) box = data.box || defaultBox();
    box = clampBox(box);
    applyBox(panel);
    root.appendChild(panel);

    new ResizeObserver(function () {
      if (!panel.isConnected || !panel.offsetWidth) return;
      if (panel.offsetWidth === box.width && panel.offsetHeight === box.height) return;
      box.width = panel.offsetWidth;
      box.height = panel.offsetHeight;
      saveBox();
    }).observe(panel);

    // Keep keystrokes and clicks inside the panel away from the page: its shortcuts
    // and "click outside closes the drawer" handlers must not react to the panel.
    ['keydown', 'keyup', 'keypress', 'copy', 'paste', 'cut',
      'mousedown', 'mouseup', 'click', 'pointerdown', 'pointerup'].forEach(function (type) {
      panel.addEventListener(type, function (e) { e.stopPropagation(); });
    });

    const header = el('header');
    header.title = 'Перетащите, чтобы передвинуть окно. Размер меняется за правый нижний угол.';
    header.addEventListener('mousedown', function (e) {
      if (e.button !== 0 || e.target.closest('button')) return;
      e.preventDefault();
      const dx = e.clientX - box.left;
      const dy = e.clientY - box.top;
      const move = function (ev) {
        box = clampBox({ left: ev.clientX - dx, top: ev.clientY - dy, width: box.width, height: box.height });
        applyBox(panel);
      };
      const up = function () {
        window.removeEventListener('mousemove', move, true);
        window.removeEventListener('mouseup', up, true);
        saveBox();
      };
      window.addEventListener('mousemove', move, true);
      window.addEventListener('mouseup', up, true);
    });

    const top = el('div', 'top');
    top.appendChild(el('div', 'title', 'Проверка синтаксиса'));
    const sideBtn = el('button', 'close', '⇆');
    sideBtn.title = 'Прижать к другому краю экрана';
    sideBtn.addEventListener('click', function () {
      const atLeft = box.left + box.width / 2 < window.innerWidth / 2;
      box = clampBox({
        left: atLeft ? window.innerWidth - box.width - 8 : 8,
        top: 8,
        width: box.width,
        height: window.innerHeight - 16,
      });
      applyBox(panel);
      saveBox();
    });
    top.appendChild(sideBtn);
    const closeBtn = el('button', 'close', '×');
    closeBtn.title = 'Закрыть (Esc)';
    closeBtn.addEventListener('click', close);
    top.appendChild(closeBtn);
    header.appendChild(top);
    panel.appendChild(header);

    const text = data.text || '';
    if (!text.trim()) {
      header.appendChild(el('div', 'summary warn', 'Не удалось получить выделенный текст'));
      const msg = el('div', 'empty');
      msg.textContent = 'Выделите код в редакторе (⌘A) и нажмите сочетание клавиш или значок ' +
        'расширения ещё раз, не щёлкая перед этим по странице. Если не помогает, вставьте текст вручную ниже.';
      panel.appendChild(msg);
      panel.appendChild(manualBox(true));
      panel.focus();
      return;
    }

    const result = JJC.check(text, { fixHint: false });
    const status = result.errors.length ? 'bad' : result.warnings.length ? 'warn' : 'ok';
    header.appendChild(el('div', 'summary ' + status, summaryText(result)));
    const lines = result.text.split('\n');
    header.appendChild(el('div', 'meta', 'Проверено: ' + lines.length + ' ' +
      plural(lines.length, 'строка', 'строки', 'строк') + ', ' + result.text.length + ' ' +
      plural(result.text.length, 'символ', 'символа', 'символов')));

    // "JSON was not checked yet / stopped at the first error": more errors may follow.
    const isNotice = function (i) {
      return i.severity === 'info' && (i.source === 'json' || i.source === 'text');
    };
    for (const issue of result.issues.filter(isNotice)) {
      header.appendChild(el('div', issue.source === 'text' ? 'notice soft' : 'notice', issue.message));
    }

    const codeBox = el('div', 'code');
    const lineNodes = renderCode(result, codeBox);

    const listed = result.issues.filter(function (i) { return !isNotice(i); });
    if (listed.length) {
      const list = el('div', 'issues');
      for (const issue of listed) list.appendChild(issueNode(result, issue, lineNodes, codeBox));
      panel.appendChild(list);
    }
    panel.appendChild(codeBox);

    if (data.clipboard === 'replaced') {
      panel.appendChild(el('div', 'hint', 'Чтобы прочитать текст из редактора, пришлось его скопировать: ' +
        'сейчас в буфере обмена выделенный код.'));
    }
    panel.appendChild(manualBox(false));
    panel.focus();
  }

  function issueNode(result, issue, lineNodes, codeBox) {
    const node = el('div', 'issue');
    const head = el('div');
    head.appendChild(el('span', 'tag ' + issue.severity, LABELS[issue.severity]));
    if (issue.length) {
      const lc = JJC.lineCol(result.text, issue.offset);
      head.appendChild(el('span', 'where', ', строка ' + lc[0] + ', колонка ' + lc[1]));
      node.addEventListener('click', function () {
        const target = lineNodes[lc[0] - 1];
        if (!target) return;
        codeBox.scrollTop += target.getBoundingClientRect().top -
          codeBox.getBoundingClientRect().top - codeBox.clientHeight / 3;
        target.classList.add('flash');
        setTimeout(function () { target.classList.remove('flash'); }, 1200);
      });
    }
    node.appendChild(head);
    node.appendChild(el('div', '', issue.message));
    if (issue.replace !== undefined) {
      const swap = el('div', 'swap');
      swap.appendChild(el('span', '', 'Заменить вручную:'));
      swap.appendChild(el('span', 'chip bad', visibleChar(result.text[issue.offset])));
      swap.appendChild(el('span', '', '→'));
      swap.appendChild(el('span', 'chip good', visibleChar(issue.replace)));
      node.appendChild(swap);
    }
    return node;
  }

  function renderCode(result, container) {
    const text = result.text;
    const sev = new Array(text.length).fill(-1);
    const lineSev = {};
    for (const issue of result.issues) {
      if (!issue.length) continue;
      const level = SEVERITY_ORDER[issue.severity];
      const end = Math.min(issue.offset + Math.max(issue.length, 1), text.length);
      for (let k = issue.offset; k < end; k++) sev[k] = Math.max(sev[k], level);
      const line = JJC.lineCol(text, issue.offset)[0];
      lineSev[line] = Math.max(lineSev[line] === undefined ? -1 : lineSev[line], level);
    }

    const pre = el('pre');
    const nodes = [];
    let offset = 0;
    text.split('\n').forEach(function (lineText, idx) {
      const number = idx + 1;
      const line = el('span', 'line' + (lineSev[number] >= 1 ? ' ' + LEVEL_NAMES[lineSev[number]] : ''));
      line.appendChild(el('span', 'ln', String(number)));
      let k = 0;
      while (k < lineText.length) {
        const level = sev[offset + k];
        let j = k;
        while (j < lineText.length && sev[offset + j] === level) j++;
        let chunk = lineText.slice(k, j);
        if (level >= 1) {
          if (!chunk.replace(/ /g, '')) chunk = chunk.replace(/ /g, '·');
          chunk = Array.from(chunk).map(function (c) { return JJC.INVISIBLE[c] ? '·' : c; }).join('');
          line.appendChild(el('mark', LEVEL_NAMES[level], chunk));
        } else {
          line.appendChild(document.createTextNode(chunk));
        }
        k = j;
      }
      pre.appendChild(line);
      nodes.push(line);
      offset += lineText.length + 1;
    });
    container.appendChild(pre);
    return nodes;
  }

  function manualBox(open) {
    const box = el('details');
    if (open) box.open = true;
    box.appendChild(el('summary', '', 'Проверить текст, вставленный вручную'));
    const area = el('textarea');
    area.placeholder = 'Вставьте сюда текст (⌘V)';
    area.spellcheck = false;
    box.appendChild(area);
    const btn = el('button', 'btn', 'Проверить');
    btn.addEventListener('click', function () {
      render({ text: area.value, how: 'manual', clipboard: 'untouched' });
    });
    box.appendChild(btn);
    return box;
  }

  window.__jjcShow = render;
})();
