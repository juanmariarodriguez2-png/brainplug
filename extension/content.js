// Brainplug capture: keeps a copy of the messages YOU send to an AI assistant.
// It never reads the answers and never talks to the network: the text goes to
// this browser's extension storage and stays there until you export or delete it.
//
// How a sent message is recognised, on any of the supported sites: you press
// Enter (or click a button) while the message box has text, and right after
// that the box is empty. No site-specific page structure is needed.
(() => {
  const SITES = {
    'chatgpt.com': 'chatgpt', 'chat.openai.com': 'chatgpt', 'claude.ai': 'claude',
    'gemini.google.com': 'gemini', 'copilot.microsoft.com': 'copilot', 'www.perplexity.ai': 'perplexity',
  };
  const site = SITES[location.hostname];
  if (!site) return;

  const BOX = 'textarea, [contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"]';
  const NAMES = /\s*[-|–—·]\s*(ChatGPT|Claude|Google Gemini|Gemini|Microsoft Copilot|Copilot|Perplexity)\s*$/i;
  const tab = Math.random().toString(36).slice(2, 8);
  let box = null, lastText = '', lastAt = 0, paused = false;

  chrome.storage.local.get('paused', got => { paused = !!got.paused; });
  chrome.storage.onChanged.addListener(changes => { if (changes.paused) paused = !!changes.paused.newValue; });

  const boxOf = el => (el && el.closest ? el.closest(BOX) : null);
  const textOf = el => (el.tagName === 'TEXTAREA' ? el.value : el.innerText || '').replace(/ /g, ' ').trim();

  function conversation() {
    // /c/<id> on ChatGPT, /chat/<id> on Claude, /app/<id> on Gemini…: the last id-looking part of the address
    const parts = location.pathname.split('/').filter(Boolean).reverse();
    const id = parts.find(p => /^[A-Za-z0-9_-]{8,}$/.test(p) && /\d/.test(p));
    return id || `new-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${tab}`;
  }
  function title() {
    const t = document.title.replace(NAMES, '').trim();
    return /^(ChatGPT|Claude|Google Gemini|Gemini|Microsoft Copilot|Copilot|Perplexity|New chat|Nuevo chat)$/i.test(t) ? '' : t.slice(0, 200);
  }
  function send(message) {
    try { chrome.runtime.sendMessage(message, () => void chrome.runtime.lastError); } catch { /* extension was reloaded */ }
  }

  function save(text) {
    const now = Date.now();
    if (text === lastText && now - lastAt < 5000) return;  // Enter and the send button can both fire
    lastText = text; lastAt = now;
    const row = { site, conv: conversation(), title: title(), ts: now, text: text.slice(0, 20000) };
    send({ type: 'capture', row });
    // a new chat only gets its address and its title a moment after the first message
    setTimeout(() => {
      const conv = conversation(), name = title();
      if (conv !== row.conv || name !== row.title) send({ type: 'fix', site, ts: now, conv, title: name });
    }, 4000);
  }

  function maybeSent(el) {
    if (paused || !el) return;
    const before = textOf(el);
    if (before.length < 2) return;
    const check = last => {
      const gone = !el.isConnected || textOf(el) === '';
      if (gone) save(before);
      else if (!last) setTimeout(() => check(true), 900);
    };
    setTimeout(() => check(false), 350);
  }

  document.addEventListener('focusin', e => { box = boxOf(e.target) || box; }, true);
  document.addEventListener('input', e => { box = boxOf(e.target) || box; }, true);
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) maybeSent(boxOf(e.target));
  }, true);
  document.addEventListener('click', e => {
    if (e.target.closest && e.target.closest('button, [role="button"]')) maybeSent(box);
  }, true);
})();
