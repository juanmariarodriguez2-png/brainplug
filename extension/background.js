// Stores captured messages, one list per month, in this browser's extension storage.
// Writes are queued so two tabs can never overwrite each other.
let queue = Promise.resolve();
const monthKey = ts => 'm:' + new Date(ts).toISOString().slice(0, 7);

async function everything() {
  const got = await chrome.storage.local.get(null);
  return Object.keys(got).filter(k => k.startsWith('m:')).sort().flatMap(k => got[k]);
}
async function add(row) {
  const key = monthKey(row.ts);
  const got = await chrome.storage.local.get([key, 'paused']);
  if (got.paused) return;
  await chrome.storage.local.set({ [key]: [...(got[key] || []), row] });
}
async function fix({ site, ts, conv, title }) {
  const key = monthKey(ts);
  const list = (await chrome.storage.local.get(key))[key] || [];
  const row = list.find(r => r.ts === ts && r.site === site);
  if (!row) return;
  if (conv) row.conv = conv;
  if (title) row.title = title;
  await chrome.storage.local.set({ [key]: list });
}
const valid = row => row && typeof row.text === 'string' && typeof row.ts === 'number' && typeof row.site === 'string';

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || sender.id !== chrome.runtime.id) return false;
  if (msg.type === 'capture' && valid(msg.row)) queue = queue.then(() => add(msg.row)).catch(() => {});
  else if (msg.type === 'fix') queue = queue.then(() => fix(msg)).catch(() => {});
  else if (msg.type === 'count') { queue.then(everything).then(items => reply({ count: items.length })); return true; }
  else if (msg.type === 'export') { queue.then(everything).then(items => reply({ items })); return true; }
  return false;
});
