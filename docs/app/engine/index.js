// Brainprint in the browser: the same pipeline as the Python package
// (files -> items -> topics, connections, layouts -> one self-contained HTML),
// with nothing leaving the tab it runs in.
import { load } from './sources.js';
import { analyse, VERSION } from './analysis.js';

export { load, analyse, VERSION };

/** Load the inputs and analyse them. Returns { payload, notes, sources }. */
export async function build(inputs, options = {}) {
  const { items, notes } = await load(inputs, options);
  const payload = analyse(items, options);
  return { payload, notes };
}

const escapeHtml = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/** Fill the viewer template (docs/app/viewer.tpl.html) exactly like brainprint/render.py does. */
export function renderHtml(template, payload, lang = 'en') {
  // Your text may contain "</script>" or "<!--" (notes about code do). Written as \u003c,
  // a "<" can never end or confuse the <script> block the data sits in.
  const data = JSON.stringify(payload).replace(/</g, '\\u003c');
  return template.split('__LANG__').join(lang === 'es' ? 'es' : 'en')
    .split('__TITLE__').join(escapeHtml(payload.meta.title))
    .replace('__DATA__', () => data);  // last, so your text is never scanned for placeholders
}
