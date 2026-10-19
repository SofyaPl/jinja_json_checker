// Runs only when the user presses the shortcut or the toolbar button. Thanks to
// "activeTab" the extension gets access to the current tab just for this moment.

const TITLE = 'Проверить выделенный текст';

chrome.action.onClicked.addListener(function (tab) {
  chrome.action.setBadgeText({ tabId: tab.id, text: '' });
  chrome.action.setTitle({ tabId: tab.id, title: TITLE });
  run(tab.id).catch(function (e) {
    const message = String(e && e.message || e);
    console.error('JSON / Jinja checker: ' + message);
    chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: '#cf222e' });
    chrome.action.setBadgeText({ tabId: tab.id, text: '!' });
    chrome.action.setTitle({ tabId: tab.id, title: 'Ошибка: ' + message });
  });
});

async function run(tabId) {
  let frameId = 0;
  try {
    const probes = await chrome.scripting.executeScript({
      target: { tabId: tabId, allFrames: true },
      func: probeFocus,
    });
    const focused = probes.find(function (p) {
      return p.result && p.result.focused && !p.result.inIframe;
    });
    if (focused) frameId = focused.frameId;
  } catch (e) {
    // Some frames may be off-limits; fall back to the top frame.
  }

  let grabbed = { text: '', how: 'none' };
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: tabId, frameIds: [frameId] },
      func: grabSelection,
    });
    if (res[0] && res[0].result) grabbed = res[0].result;
  } catch (e) {
    grabbed.error = String(e && e.message || e);
  }
  try {
    grabbed.box = (await chrome.storage.local.get('panelBox')).panelBox || null;
  } catch (e) {
    grabbed.box = null;
  }

  await chrome.scripting.executeScript({
    target: { tabId: tabId, frameIds: [0] },
    files: ['checker.js', 'panel.js'],
  });
  await chrome.scripting.executeScript({
    target: { tabId: tabId, frameIds: [0] },
    func: function (data) { window.__jjcShow(data); },
    args: [grabbed],
  });
}

// The functions below are injected into the page and must be self-contained.

function probeFocus() {
  const ae = document.activeElement;
  return {
    focused: document.hasFocus(),
    inIframe: !!ae && (ae.tagName === 'IFRAME' || ae.tagName === 'FRAME'),
  };
}

async function grabSelection() {
  const ae = document.activeElement;
  const inCodeEditor = !!(ae && ae.closest && ae.closest('.monaco-editor, .cm-editor, .CodeMirror, .ace_editor'));

  // Plain text fields: read the selection directly, the clipboard is not touched.
  if (ae && !inCodeEditor && (ae.tagName === 'TEXTAREA' ||
      (ae.tagName === 'INPUT' && /^(text|search|url|)$/i.test(ae.type || '')))) {
    const t = ae.value.substring(ae.selectionStart, ae.selectionEnd);
    if (t) return { text: t, how: 'field', clipboard: 'untouched' };
  }
  if (!inCodeEditor) {
    const sel = window.getSelection ? String(window.getSelection()) : '';
    return { text: sel, how: sel ? 'selection' : 'none', clipboard: 'untouched' };
  }

  // Code editors draw text themselves and only hand it out through a copy event.
  // Try to remember what was in the clipboard to put it back, but never ask the
  // user for permission: if reading is not already allowed, skip it.
  let previous = null;
  try {
    const perm = await navigator.permissions.query({ name: 'clipboard-read' });
    if (perm.state === 'granted') previous = await navigator.clipboard.readText();
  } catch (e) {
    previous = null;
  }

  let captured = null;
  const onCopy = function (e) {
    captured = e.clipboardData ? e.clipboardData.getData('text/plain') : null;
    if (captured && previous !== null) {
      e.clipboardData.setData('text/plain', previous);
      e.preventDefault();
    }
  };
  window.addEventListener('copy', onCopy);
  try {
    document.execCommand('copy');
  } catch (e) {
    // ignore, fall through to the selection
  } finally {
    window.removeEventListener('copy', onCopy);
  }
  if (captured) {
    return { text: captured, how: 'copy', clipboard: previous !== null ? 'restored' : 'replaced' };
  }

  const sel = window.getSelection ? String(window.getSelection()) : '';
  if (sel) return { text: sel, how: 'selection', clipboard: 'untouched' };
  return { text: '', how: 'none', clipboard: 'untouched' };
}
