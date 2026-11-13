// Runs only on the Brainprint web app. When the page asks, it hands over the
// messages saved by this extension, so you do not have to export and re-import
// a file. The hand-over happens inside your browser: nothing crosses the network.
window.addEventListener('message', event => {
  const msg = event.data;
  if (event.source !== window || !msg || msg.source !== 'brainprint-app') return;
  const reply = data => window.postMessage({ source: 'brainprint-ext', ...data }, location.origin);
  try {
    if (msg.type === 'hello') chrome.runtime.sendMessage({ type: 'count' }, got => { if (!chrome.runtime.lastError && got && got.count) reply({ type: 'count', count: got.count }); });
    if (msg.type === 'get') chrome.runtime.sendMessage({ type: 'export' }, got => { if (!chrome.runtime.lastError && got) reply({ type: 'items', items: got.items }); });
  } catch { /* extension was reloaded: the page simply does not show the offer */ }
});
