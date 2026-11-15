// Read everything you have written into one common format.
// A port of brainplug/sources.py that runs in the browser (and in Node, for tests).
// Every loader keeps only your own words: your side of a chat, your notes, the text
// you typed in an email, your side of a WhatsApp chat.
import { blobFile, bytesFile, listZip, concat, ZIP_LIMITS, ZipSkip } from './zip.js';

export const MAX_NOTE = 400000;
const NOTE_SUFFIXES = new Set(['.md', '.markdown', '.txt']);
const SKIP_DIRS = new Set(['node_modules', 'templates', 'Templates', '__MACOSX']);
const NOTION_ID = /\s[0-9a-f]{32}$/;
const WA_MIN_WORDS = 12;
const GEMINI_GAP = 30 * 60 * 1000;
const utf8 = new TextDecoder('utf-8');

export const countWords = text => { const t = text.trim(); return t ? t.split(/\s+/).length : 0; };
const item = (id, title, created, source, kind, text, extra = {}) =>
  ({ id, title, created, source, kind, text, parts: [], size: 1, links: [], tags: [], dated: true, ...extra, words: countWords(text) });
const suffix = path => { const m = /\.[^./]+$/.exec(path); return m ? m[0].toLowerCase() : ''; };
const baseName = path => path.slice(path.lastIndexOf('/') + 1);
const stem = path => baseName(path).replace(/\.[^.]+$/, '');
const squash = s => s.replace(/\s+/g, ' ').trim();

// ------------------------------------------------------------------ dates
const MONTHS = {};
['january enero jan ene', 'february febrero feb', 'march marzo mar', 'april abril apr abr', 'may mayo',
  'june junio jun', 'july julio jul', 'august agosto aug ago', 'september septiembre sep sept',
  'october octubre oct', 'november noviembre nov', 'december diciembre dec dic']
  .forEach((names, i) => names.split(' ').forEach(n => { MONTHS[n] = i + 1; }));

/** Tolerant date parser: ISO, 03/03/2025, 'March 3, 2025 10:00 AM', '3 de marzo de 2025'. Returns ms or null. */
export function parseDate(value) {
  if (value == null || value === '') return null;
  const s = String(value).trim().replace(/^["']+|["']+$/g, '');
  const iso = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?\s*(Z|[+-]\d{2}:?\d{2})?$/.exec(s);
  if (iso) {
    const t = Date.parse(`${iso[1]}T${iso[2] || '00:00'}${iso[3] || 'Z'}`);
    if (!Number.isNaN(t)) return t;
  }
  let hour = 0, minute = 0, y = null, mo = null, d = null, m;
  const t = /(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp])?/.exec(s);
  if (t) {
    hour = +t[1] % 24; minute = +t[2];
    if (t[3]) hour = hour % 12 + (t[3].toLowerCase() === 'p' ? 12 : 0);
  }
  if ((m = /(\d{4})-(\d{1,2})-(\d{1,2})/.exec(s))) [y, mo, d] = [+m[1], +m[2], +m[3]];
  if (y === null && (m = /(\d{1,2})[/.](\d{1,2})[/.](\d{4})/.exec(s))) [d, mo, y] = [+m[1], +m[2], +m[3]];
  if (y === null && (m = /(\p{L}+)\.?\s+(\d{1,2}),?\s+(\d{4})/u.exec(s)) && MONTHS[m[1].toLowerCase()]) {
    [mo, d, y] = [MONTHS[m[1].toLowerCase()], +m[2], +m[3]];
  }
  if (y === null && (m = /(\d{1,2})\s+(?:de\s+)?(\p{L}+)\.?,?\s+(?:de\s+)?(\d{4})/u.exec(s)) && MONTHS[m[2].toLowerCase()]) {
    [d, mo, y] = [+m[1], MONTHS[m[2].toLowerCase()], +m[3]];
  }
  if (y === null || mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const out = Date.UTC(y, mo - 1, d, hour, minute);
  return new Date(out).getUTCDate() === d ? out : null;
}

// python-docx, which AI assistants often use to write Word files, stamps every new document with
// the date of its own template, so those files all claim to be from 23 December 2013.
const TEMPLATE_DATES = new Set([Date.UTC(2013, 11, 23, 23, 15)]);
const EARLIEST = Date.UTC(1990, 0, 1);

/** A document's own date, unless it is a known placeholder or impossible. */
function realDate(value) {
  const when = typeof value === 'number' ? value : parseDate(value);
  if (when == null || !Number.isFinite(when) || TEMPLATE_DATES.has(when) || when < EARLIEST) return null;
  return when > Date.now() + 2 * 86400000 ? null : when;
}
const fromEpoch = v => (typeof v === 'number' && v > 0 && Number.isFinite(v) ? v * 1000
  : (typeof v === 'string' && +v > 0 ? +v * 1000 : null));

// ------------------------------------------------------------- AI chats
function chatgptText(content) {
  const out = [];
  for (const part of content.parts || []) {
    if (typeof part === 'string') out.push(part);
    else if (part && typeof part.text === 'string') out.push(part.text);
  }
  if (!out.length && typeof content.text === 'string') out.push(content.text);
  return out.filter(p => p.trim()).join('\n').trim();
}

export function parseChatgpt(data) {
  const items = [];
  data.forEach((conv, i) => {
    if (!conv || typeof conv !== 'object') return;
    const mine = []; let total = 0;
    for (const node of Object.values(conv.mapping || {})) {
      const msg = node && node.message;
      if (!msg) continue;
      const role = (msg.author || {}).role;
      if (role !== 'user' && role !== 'assistant') continue;
      const text = chatgptText(msg.content || {});
      if (!text) continue;
      total++;
      if (role === 'user') mine.push([fromEpoch(msg.create_time), text]);
    }
    const first = mine.find(m => m[0]);
    const created = fromEpoch(conv.create_time) ?? (first ? first[0] : null);
    if (created === null || !mine.length) return;
    mine.sort((a, b) => (a[0] ?? created) - (b[0] ?? created));
    items.push(item(`chatgpt:${conv.id || conv.conversation_id || i}`, (conv.title || 'Untitled').trim() || 'Untitled',
      created, 'chatgpt', 'chat', mine.map(m => m[1]).join('\n'),
      { parts: mine.map(m => m[0] ?? created), size: total, msgs: mine.map(m => m[1]) }));
  });
  return items;
}

export function parseClaude(data) {
  const items = [];
  data.forEach((conv, i) => {
    if (!conv || typeof conv !== 'object') return;
    const mine = []; let total = 0;
    for (const msg of conv.chat_messages || []) {
      if (msg.sender !== 'human' && msg.sender !== 'assistant') continue;
      let text = (msg.text || '').trim();
      if (!text) text = (msg.content || []).filter(c => c && c.type === 'text').map(c => c.text || '').join('\n').trim();
      if (!text) continue;
      total++;
      if (msg.sender === 'human') mine.push([parseDate(msg.created_at), text]);
    }
    const first = mine.find(m => m[0]);
    const created = parseDate(conv.created_at) ?? (first ? first[0] : null);
    if (created === null || !mine.length) return;
    items.push(item(`claude:${conv.uuid || i}`, (conv.name || '').trim() || 'Untitled', created, 'claude', 'chat',
      mine.map(m => m[1]).join('\n'), { parts: mine.map(m => m[0] ?? created), size: total, msgs: mine.map(m => m[1]) }));
  });
  return items;
}

// --------------------------------------------------------------- Gemini
const GEMINI_PREFIX = /^(?:Prompted|Said|Asked|You said|Has preguntado|Preguntaste|Has dicho|Dijiste|Le has dicho|Le has preguntado|Solicitaste|Has pedido)[:\s ]+/i;
const GEMINI_SKIP = /^(?:Used|Gave feedback|Selected|Created|Usaste|Has usado|Has utilizado|Enviaste comentarios|Has enviado comentarios)(?![\p{L}\p{N}_])/iu;

const isGemini = e => {
  if (!e || typeof e !== 'object' || !('time' in e) || !('title' in e)) return false;
  const tag = [e.header || '', ...(e.products || [])].join(' ').toLowerCase();
  return tag.includes('gemini') || tag.includes('bard');
};
const stamp = ms => new Date(ms).toISOString().replace(/[-:]/g, '').slice(0, 15);

function geminiItems(prompts) {
  prompts.sort((a, b) => a[0] - b[0]);
  const groups = new Map();
  let last = null, session = 0;
  for (const [when, text, conv] of prompts) {
    let key = 'c:' + conv;
    if (!conv) {
      if (last === null || when - last > GEMINI_GAP) session++;
      last = when; key = 's:' + session;
    }
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push([when, text]);
  }
  return [...groups].map(([key, turns]) => {
    const title = squash(turns[0][1]);
    return item(key.startsWith('c:') ? `gemini:${key.slice(2)}` : `gemini:${stamp(turns[0][0])}`,
      title.slice(0, 70) + (title.length > 70 ? '…' : ''), turns[0][0], 'gemini', 'chat',
      turns.map(t => t[1]).join('\n'), { parts: turns.map(t => t[0]), size: 2 * turns.length, msgs: turns.map(t => t[1]) });
  });
}

export function parseGemini(data) {
  const prompts = [];
  for (const entry of data) {
    if (!isGemini(entry)) continue;
    const when = parseDate(entry.time);
    let text = '';
    for (const detail of entry.details || []) {
      if (detail && ['request', 'prompt', 'solicitud'].includes(String(detail.name || '').toLowerCase())) text = String(detail.value || '');
    }
    if (!text) {
      const title = unescapeHtml(String(entry.title || '')).trim();
      if (GEMINI_SKIP.test(title)) continue;
      text = title.replace(GEMINI_PREFIX, '');
    }
    text = text.trim();
    if (when === null || !text) continue;
    const conv = /\/app\/(?:c\/)?([0-9a-zA-Z_-]{6,})/.exec(String(entry.titleUrl || ''));
    prompts.push([when, text, conv ? conv[1] : '']);
  }
  return geminiItems(prompts);
}

export function parseGeminiHtml(markup) {
  const prompts = [];
  for (const cell of markup.split('<div class="outer-cell').slice(1)) {
    if (!/Gemini|Bard/.test(cell.slice(0, 600))) continue;
    const m = /content-cell[^"]*mdl-typography--body-1">([\s\S]*?)<br\s*\/?>([\s\S]*?)<br/.exec(cell);
    if (!m) continue;
    const title = unescapeHtml(m[1].replace(/<[^>]+>/g, ' ')).replace(/ /g, ' ').trim();
    const when = parseDate(unescapeHtml(m[2].replace(/<[^>]+>/g, ' ')).replace(/ /g, ' '));
    if (when === null || GEMINI_SKIP.test(title)) continue;
    const text = title.replace(GEMINI_PREFIX, '').trim();
    if (text) prompts.push([when, text, '']);
  }
  return geminiItems(prompts);
}

// ---------------------------------------------- coding agents: Claude Code and Codex
// Text the tools put on your side of a session: environment blocks, instructions, command echoes.
const INJECTED = /^\s*(?:<(?:environment_context|user_instructions|user_shell_command|turn_aborted|system-reminder|task-notification|user-prompt-submit-hook|command-[a-z]+|local-command-[a-z]+|bash-[a-z]+)\b|# AGENTS\.md instructions|Caveat: The messages below|\[Request interrupted)/i;
// Keys and tokens people paste into a coding session by mistake.
export const SECRET = /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g;
const typed = value => {
  const text = String(value ?? '').trim();
  return !text || INJECTED.test(text) ? '' : text.replace(SECRET, '[secret]');
};
const textBlocks = content => (typeof content === 'string' ? content
  : (Array.isArray(content) ? content : []).filter(b => b && typeof b === 'object' && (b.type === 'text' || b.type === 'input_text')).map(b => b.text || '').join('\n'));

// One Claude Code or Codex session log (JSON Lines). Keeps what you typed, never the agent's work.
export function parseSession(text, fallbackId) {
  let kind = '', sid = '', cwd = '', title = '', start = null, answers = 0;
  let mine = []; const queued = [], events = [];
  for (const raw of text.split('\n')) {
    let obj;
    try { obj = JSON.parse(raw); } catch { continue; }
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) continue;
    const when = parseDate(obj.timestamp) ?? start;
    if ('sessionId' in obj || obj.type === 'summary') {  // Claude Code
      if (!kind && 'sessionId' in obj) kind = 'claudecode';
      sid = obj.sessionId || sid; cwd = obj.cwd || cwd;
      if (obj.type === 'summary') title = title || String(obj.summary || '');
      else if (obj.type === 'user' && !obj.isSidechain && !obj.isMeta) {
        const t = typed(textBlocks((obj.message || {}).content));
        if (t && when !== null) mine.push([when, t]);
      } else if (obj.type === 'queue-operation' && obj.operation === 'enqueue') {
        const t = typed(textBlocks(obj.content));  // typed while the agent was working
        if (t && when !== null) queued.push([when, t]);
      } else if (obj.type === 'attachment' && obj.attachment && obj.attachment.type === 'queued_command') {
        const sent = obj.attachment;  // a message delivered while it worked, e.g. with a screenshot
        if (sent.humanTurn === true || (sent.origin || {}).kind === 'human') {
          const t = typed(textBlocks(sent.prompt));
          if (t && when !== null) queued.push([when, t]);
        }
      } else if (obj.type === 'assistant' && !obj.isSidechain) answers += textBlocks((obj.message || {}).content).trim() ? 1 : 0;
      continue;
    }
    const p = obj.payload && typeof obj.payload === 'object' && !Array.isArray(obj.payload) ? obj.payload : obj;  // Codex, new and old logs
    if (obj.type === 'session_meta' || ('instructions' in obj && 'id' in obj)) {
      kind = 'codex'; sid = String(p.id || sid); cwd = String(p.cwd || cwd);
      start = parseDate(p.timestamp) ?? start;
      continue;
    }
    const at = when ?? start;
    if (p.type === 'message' && p.role === 'user') {
      const t = typed(textBlocks(p.content));
      if (t && at !== null) mine.push([at, t]);
    } else if (p.type === 'message' && p.role === 'assistant') answers++;
    else if (p.type === 'user_message') {
      const t = typed(p.message);
      if (t && at !== null) events.push([at, t]);
    }
  }
  if (!kind) return null;
  if (kind === 'codex' && !mine.length) mine = events;  // older logs only record what you typed as events
  const left = new Map();
  for (const [, t] of mine) left.set(squash(t), (left.get(squash(t)) || 0) + 1);
  const seen = new Set();
  for (const [w, t] of queued) {  // a message typed while the agent worked is logged more than once
    const key = squash(t);
    if (seen.has(key)) continue;
    seen.add(key);
    const n = left.get(key) || 0;
    if (n) left.set(key, n - 1); else mine.push([w, t]);
  }
  mine.sort((a, b) => a[0] - b[0]);
  if (!mine.length) return null;
  const project = cwd ? cwd.replace(/[\\/]+$/, '').split(/[\\/]/).pop() : '';
  const first = squash(title || mine[0][1]);
  const name = first.slice(0, 70) + (first.length > 70 ? '…' : '');
  return item(`${kind}:${sid || fallbackId}`, project ? `${project} · ${name}` : name, mine[0][0], kind, 'chat',
    mine.map(m => m[1]).join('\n'), { parts: mine.map(m => m[0]), msgs: mine.map(m => m[1]), size: mine.length + answers });
}

// ---------------------------------------------------------- live capture
export function parseCapture(data) {
  const groups = new Map();
  for (const row of data.items || []) {
    if (!row || typeof row !== 'object') continue;
    const text = String(row.text || '').trim();
    const when = typeof row.ts === 'number' ? (row.ts > 0 ? row.ts : null) : parseDate(row.ts);
    const site = String(row.site || 'other').toLowerCase().replace(/[^a-z0-9]/g, '') || 'other';
    if (!text || when === null) continue;
    const conv = String(row.conv || stamp(when).slice(0, 8));
    const key = site + '\u0000' + conv;
    if (!groups.has(key)) groups.set(key, { site, conv, turns: [] });
    groups.get(key).turns.push([when, text, String(row.title || '')]);
  }
  return [...groups.values()].map(({ site, conv, turns }) => {
    turns.sort((a, b) => a[0] - b[0]);
    const named = [...turns].reverse().find(t => t[2].trim());
    const title = named ? named[2] : squash(turns[0][1]).slice(0, 70);
    return item(`${site}:${conv}`, title.trim(), turns[0][0], site, 'chat', turns.map(t => t[1]).join('\n'),
      { parts: turns.map(t => t[0]), size: 2 * turns.length, msgs: turns.map(t => t[1]) });
  });
}

export function parseJson(data) {
  if (data && !Array.isArray(data) && data.format === 'brainplug-capture') return parseCapture(data);
  if (Array.isArray(data) && data.length) {
    const sample = data.find(c => c && typeof c === 'object' && !Array.isArray(c)) || {};
    if ('mapping' in sample) return parseChatgpt(data);
    if ('chat_messages' in sample) return parseClaude(data);
    if (data.slice(0, 50).some(isGemini)) return parseGemini(data);
  }
  throw new Error('Unknown JSON: expected conversations.json from ChatGPT or Claude, MyActivity.json from Gemini (Google Takeout) or a Brainplug capture file.');
}

// ----------------------------------------- notes: Obsidian, Notion, folders
function frontmatter(text) {
  if (!text.startsWith('---')) return [{}, text];
  const end = text.indexOf('\n---', 3);
  if (end < 0) return [{}, text];
  const meta = {};
  let key = null;
  const strip = v => v.trim().replace(/^["']+|["']+$/g, '');
  for (const line of text.slice(3, end).split(/\r?\n/)) {
    if (key && /^\s*-\s+\S/.test(line)) {
      if (!Array.isArray(meta[key])) meta[key] = [];
      meta[key].push(strip(line.slice(line.indexOf('-') + 1)));
    } else if (line.includes(':') && !/^\s/.test(line)) {
      const at = line.indexOf(':');
      key = line.slice(0, at).trim().toLowerCase();
      const val = line.slice(at + 1).trim();
      meta[key] = val.startsWith('[') && val.endsWith(']')
        ? val.slice(1, -1).split(',').map(strip).filter(Boolean) : strip(val);
    }
  }
  return [meta, text.slice(end + 4)];
}

/** Returns [plain text, linked titles, tags] for a Markdown note. */
export function cleanMarkdown(body) {
  body = body.replace(/```[\s\S]*?```/g, ' ');
  const links = [...body.matchAll(/(?<!!)\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]/g)].map(m => m[1]);
  links.push(...[...body.matchAll(/\[([^\]]+)\]\([^)\s]*[0-9a-f]{32}\.md\)/g)].map(m => m[1]));
  body = body.replace(/!\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[\[[^\]|]*\|([^\]]+)\]\]/g, '$1').replace(/\[\[([^\]]+)\]\]/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/https?:\/\/\S+|<[^>\n]+>/g, ' ');
  const tags = [...body.matchAll(/(?<![\p{L}\p{N}_/&])#(\p{L}[\p{L}\p{N}_/-]*)/gu)].map(m => m[1]);
  body = body.replace(/^\s*(#{1,6}|[-*+>]|\d+[.)])\s+/gm, '')
    .replace(/[*_~`|]{1,3}|(?<![\p{L}\p{N}_/&])#(?=\p{L})/gu, ' ');
  return [squash(body), links.map(l => l.trim()).filter(Boolean), tags];
}

const DATE_KEYS = ['created', 'date created', 'created time', 'created at', 'created_at', 'creado',
  'fecha de creación', 'date', 'fecha', 'last edited time', 'last edited', 'updated'];
function metaDate(meta) {
  for (const key of DATE_KEYS) {
    if (key in meta) { const found = parseDate(meta[key]); if (found !== null) return found; }
  }
  return null;
}

// Notes Brainplug wrote itself are a copy of things already read, so they are skipped;
// the memory folder and "About me" are read as the source "memory".
const GENERATED = /(?:^|\/)Brainplug\/(?:Items\/|Topics\/|Brainplug\.md$|Excluded\.md$|Topic names\.md$)/;
const TOPIC_NAMES = /(?:^|\/)Brainplug\/Topic names\.md$/;
const NAME_LINE = /^\s*[-*]\s+\*\*(.+?)\*\*\s+·\s+(.+?)\s*$/;
const EXCLUDED = /(?:^|\/)Brainplug\/Excluded\.md$/;
const EXCLUDED_LINE = /^\s*[-*]\s+(source:\s*)?`([^`]+)`/;
const MEMORY = /(?:^|\/)Brainplug\/(?:Memory\/|About me\.md$)/;

function parseNote(text, path, rel, source, mtime) {
  const [meta, body] = frontmatter(text.slice(0, MAX_NOTE));
  if (source === 'memory') {
    if (String(meta.archived || '').toLowerCase() === 'true') return null;  // a memory that was put away
    if (body.includes('brainplug: fill this in') && !/^- [^:\n]+:[ \t]*\S/m.test(body)) return null;  // "About me" is still the empty template
  }
  const [clean, links, tags] = cleanMarkdown(body);
  if (countWords(clean) < 3) return null;
  let created = metaDate(meta);
  if (created === null) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(stem(path));  // daily notes
    created = m ? parseDate(m[0]) : null;
  }
  let extra = meta.tags || [];
  if (!Array.isArray(extra)) extra = String(extra).split(/[,\s]+/);
  const all = [...new Set([...tags, ...extra].filter(Boolean).map(t => t.replace(/^#+/, '')))].sort();
  return item(`${source}:${rel}`, stem(path), created ?? mtime, source, 'note', clean, { links, tags: all });
}

function parseNotionPage(text, path, rel, mtime) {
  const lines = text.slice(0, MAX_NOTE).split(/\r?\n/);
  let title = stem(path).replace(NOTION_ID, ''), i = 0;
  if (lines.length && lines[0].startsWith('# ')) { title = lines[0].slice(2).trim() || title; i = 1; }
  while (i < lines.length && !lines[i].trim()) i++;
  const props = {};
  while (i < lines.length && /^\p{L}[^:\n]{0,40}:\s+\S/u.test(lines[i])) {
    const at = lines[i].indexOf(':');
    props[lines[i].slice(0, at).trim().toLowerCase()] = lines[i].slice(at + 1).trim();
    i++;
  }
  const [clean, links, tags] = cleanMarkdown(lines.slice(i).join('\n'));
  if (countWords(clean) < 3) return null;
  const created = metaDate(props);
  for (const key of ['tags', 'etiquetas', 'tag']) tags.push(...(props[key] || '').split(',').map(t => t.trim()).filter(Boolean));
  return item(`notion:${rel}`, title, created ?? mtime, 'notion', 'note', clean,
    { links, tags: [...new Set(tags)].sort(), dated: created !== null });
}

// ---------------------------------------------------------------- Gmail
const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', aacute: 'á', eacute: 'é', iacute: 'í',
  oacute: 'ó', uacute: 'ú', ntilde: 'ñ', Aacute: 'Á', Eacute: 'É', Iacute: 'Í', Oacute: 'Ó', Uacute: 'Ú', Ntilde: 'Ñ',
  uuml: 'ü', Uuml: 'Ü', iexcl: '¡', iquest: '¿', ccedil: 'ç', agrave: 'à', egrave: 'è', ograve: 'ò', euro: '€',
  ndash: '–', mdash: '—', hellip: '…', lsquo: '‘', rsquo: '’', ldquo: '“', rdquo: '”', laquo: '«', raquo: '»', copy: '©' };
export function unescapeHtml(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (all, code) => {
    if (code[0] === '#') {
      const n = code[1].toLowerCase() === 'x' ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
      return n > 0 && n < 0x110000 ? String.fromCodePoint(n) : all;
    }
    return ENTITIES[code] ?? all;
  });
}
const htmlToText = markup => unescapeHtml(markup.replace(/<(script|style|blockquote)\b[\s\S]*?<\/\1>/gi, ' ')
  .replace(/<br\s*\/?>|<\/p>|<\/div>/gi, '\n').replace(/<[^>]+>/g, ' '));

const REPLY = new RegExp([
  '^(?:On|El|Le)\\b[^\\n]{0,200}\\n?[^\\n]{0,120}(?:wrote|escribió|a écrit)\\s?:\\s*$',
  '^-{2,}\\s*(?:Original Message|Mensaje original|Forwarded message|Mensaje reenviado)\\s*-{2,}\\s*$',
  '^(?:From|De):\\s.+\\n(?:Sent|Enviado|Date|Fecha)(?: el)?:\\s',
  '^(?:Sent from my|Enviado desde mi)\\s.+$',
  '^-- ?$'].join('|'), 'mi');

/** Keep only what the sender typed: drop quoted replies and signatures. */
export function stripQuoted(text) {
  text = text.replace(/\r\n/g, '\n');
  const m = REPLY.exec(text);
  if (m) text = text.slice(0, m.index);
  const lines = text.split('\n').filter(l => !l.trimStart().startsWith('>'));
  return squash(lines.join('\n').replace(/https?:\/\/\S+/g, ' '));
}

function indexOfSeq(buf, seq, from) {
  outer: for (let i = buf.indexOf(seq[0], from); i >= 0 && i + seq.length <= buf.length; i = buf.indexOf(seq[0], i + 1)) {
    for (let j = 1; j < seq.length; j++) if (buf[i + j] !== seq[j]) continue outer;
    return i;
  }
  return -1;
}
const FROM = [10, 70, 114, 111, 109, 32];  // "\nFrom "

const startsWithFrom = buf => buf.length >= 5 && buf[0] === 70 && buf[1] === 114 && buf[2] === 111 && buf[3] === 109 && buf[4] === 32;

/** Stream an mbox as one Uint8Array per message, without holding the mailbox in memory. */
async function* mboxMessages(file) {
  let buf = null, start = -1, scan = 0;  // start: where the current message begins in buf
  for await (const chunk of file.chunks()) {
    buf = buf && buf.length ? concat([buf, chunk]) : chunk;
    if (start < 0) {  // find the first "From " line
      const at = startsWithFrom(buf) ? 0 : indexOfSeq(buf, FROM, 0);
      if (at < 0) { buf = buf.subarray(Math.max(0, buf.length - 5)); continue; }
      const eol = buf.indexOf(10, startsWithFrom(buf) ? 0 : at + 1);
      if (eol < 0) { buf = buf.subarray(at); continue; }
      start = eol + 1; scan = start;
    }
    let hold = -1;
    for (;;) {
      const i = indexOfSeq(buf, FROM, scan);
      if (i < 0) break;
      // a new message starts at a "From " line that follows a blank line
      const blank = i === start || buf[i - 1] === 10 || (buf[i - 1] === 13 && (i - 1 === start || buf[i - 2] === 10));
      if (!blank) { scan = i + 1; continue; }
      const eol = buf.indexOf(10, i + 1);
      if (eol < 0) { hold = i; break; }  // the "From " line itself is not complete yet
      yield buf.subarray(start, i + 1);
      start = eol + 1; scan = start;
    }
    scan = (hold >= 0 ? hold : Math.max(scan, buf.length - 5)) - start;
    buf = buf.subarray(start); start = 0;
  }
  if (start >= 0 && buf && buf.length > start) yield buf.subarray(start);
}

function splitMessage(raw) {
  if (raw[0] === 10) return [raw.subarray(0, 0), raw.subarray(1)];  // no headers at all
  if (raw[0] === 13 && raw[1] === 10) return [raw.subarray(0, 0), raw.subarray(2)];
  let cut = indexOfSeq(raw, [10, 10], 0), skip = 2;
  const crlf = indexOfSeq(raw, [13, 10, 13, 10], 0);
  if (crlf >= 0 && (cut < 0 || crlf < cut)) { cut = crlf; skip = 4; }
  return cut < 0 ? [raw, new Uint8Array(0)] : [raw.subarray(0, cut), raw.subarray(cut + skip)];
}

function parseHeaders(bytes) {
  const out = new Map();
  const lines = utf8.decode(bytes).split(/\r?\n/);
  let name = null;
  for (const line of lines) {
    if (/^[ \t]/.test(line) && name) { out.set(name, out.get(name) + ' ' + line.trim()); continue; }
    const at = line.indexOf(':');
    if (at <= 0) { name = null; continue; }
    const key = line.slice(0, at).trim().toLowerCase();
    if (out.has(key)) { name = null; continue; }  // like email.message: the first one wins
    name = key; out.set(key, line.slice(at + 1).trim());
  }
  return out;
}
const addresses = value => (value || '').toLowerCase().match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g) || [];

function decodeBytes(bytes, charset) {
  try { return new TextDecoder((charset || 'utf-8').trim().toLowerCase()).decode(bytes); } catch { return utf8.decode(bytes); }
}
function base64Bytes(text) {
  const bin = atob(text.replace(/[^A-Za-z0-9+/]/g, ''));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function qpBytes(text, header = false) {
  if (header) text = text.replace(/_/g, ' ');
  text = text.replace(/=\r?\n/g, '');
  const out = [];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '=' && /^[0-9A-Fa-f]{2}$/.test(text.slice(i + 1, i + 3))) { out.push(parseInt(text.slice(i + 1, i + 3), 16)); i += 2; } else out.push(text.charCodeAt(i) & 255);
  }
  return Uint8Array.from(out);
}
const decodeWords = value => (value || '').replace(/=\?([^?]+)\?([bBqQ])\?([^?]*)\?=(?:\s+(?==\?))?/g, (all, charset, kind, data) => {
  try { return decodeBytes(kind.toLowerCase() === 'b' ? base64Bytes(data) : qpBytes(data, true), charset); } catch { return all; }
});
const param = (value, name) => {
  const m = new RegExp(`${name}\\s*=\\s*(?:"([^"]*)"|([^;\\s]+))`, 'i').exec(value || '');
  return m ? (m[1] ?? m[2]) : '';
};
const latin1 = bytes => { let s = ''; for (let i = 0; i < bytes.length; i += 32768) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768)); return s; };

/** The text a person would read: the first text/plain part, else the first text/html one. */
function bodyText(headers, body, depth = 0) {
  const type = (headers.get('content-type') || 'text/plain').toLowerCase();
  if (/attachment/i.test(headers.get('content-disposition') || '')) return null;
  if (type.startsWith('multipart/') && depth < 6) {
    const boundary = param(headers.get('content-type'), 'boundary');
    if (!boundary) return null;
    const mark = Array.from(new TextEncoder().encode('--' + boundary));
    let html = null, at = indexOfSeq(body, mark, 0);
    while (at >= 0) {
      if (body[at + mark.length] === 45 && body[at + mark.length + 1] === 45) break;  // closing boundary
      const next = indexOfSeq(body, mark, at + mark.length);
      const from = body.indexOf(10, at);
      if (from < 0 || (next >= 0 && from > next)) break;
      const part = body.subarray(from + 1, next < 0 ? body.length : next);
      const [h, b] = splitMessage(part);
      const found = bodyText(parseHeaders(h), b, depth + 1);
      if (found && !found.html) return found;
      if (found && !html) html = found;
      at = next;
    }
    return html;
  }
  if (!type.startsWith('text/plain') && !type.startsWith('text/html')) return null;
  const enc = (headers.get('content-transfer-encoding') || '').toLowerCase();
  let bytes = body;
  try {
    if (enc === 'base64') bytes = base64Bytes(latin1(body));
    else if (enc === 'quoted-printable') bytes = qpBytes(latin1(body));
  } catch { return null; }
  return { text: decodeBytes(bytes, param(headers.get('content-type'), 'charset')), html: type.startsWith('text/html') };
}

/** Read the mail you sent from a Takeout mbox, grouped by thread. */
export async function loadGmail(file, me = [], note = () => {}) {
  let mine = new Set(me.map(a => a.toLowerCase()));
  if (!mine.size) {
    // Your own address is the one mail is delivered to (or, in a Sent-only mailbox, the one everything comes from).
    const seen = new Map();
    for await (const raw of mboxMessages(file)) {
      const h = parseHeaders(splitMessage(raw)[0]);
      for (const a of [...addresses(h.get('from')), ...addresses(h.get('delivered-to'))]) seen.set(a, (seen.get(a) || 0) + 1);
    }
    if (!seen.size) return [];
    const ranked = [...seen].sort((a, b) => b[1] - a[1]);
    const [address, count] = ranked[0];
    mine = new Set([address]);
    const reasons = [];
    if (count * 2 < [...seen.values()].reduce((a, b) => a + b, 0)) reasons.push('the address appears in fewer than half of the counted addresses');
    // A runner-up within 20% of the leader is too close to trust silently.
    if (ranked.length > 1 && ranked[1][1] * 5 >= count * 4) reasons.push('two addresses have similar counts');
    const unsure = reasons.length ? `; unsure: ${reasons.join('; ')}` : '';
    note(`Gmail: kept the mail sent from ${address} (detected${unsure}; to change it, give your address in “Who you are” or with --me).`);
  }
  const threads = new Map();
  for await (const raw of mboxMessages(file)) {
    const [head, body] = splitMessage(raw);
    const h = parseHeaders(head);
    if (!addresses(h.get('from')).some(a => mine.has(a))) continue;
    const found = bodyText(h, body);
    const when = Date.parse((h.get('date') || '').replace(/\s*\([^)]*\)\s*$/, ''));
    if (!found || Number.isNaN(when)) continue;
    const text = stripQuoted(found.html ? htmlToText(found.text) : found.text).slice(0, MAX_NOTE);
    if (!text) continue;
    const subject = decodeWords(h.get('subject')).replace(/^\s*(?:(?:re|fwd?|rv|fw|tr)\s*:\s*)+/i, '').trim();
    const key = (h.get('x-gm-thrid') || '').trim() || subject.toLowerCase();
    if (!threads.has(key)) threads.set(key, { subject, parts: [] });
    threads.get(key).parts.push([when, text]);
  }
  const items = [];
  for (const [key, thread] of threads) {
    const parts = thread.parts.sort((a, b) => a[0] - b[0]);
    const text = parts.map(p => p[1]).join('\n');
    if (countWords(text) < 3) continue;
    items.push(item(`gmail:${key}`, thread.subject || '(no subject)', parts[0][0], 'gmail', 'message', text,
      { parts: parts.map(p => p[0]), size: parts.length }));
  }
  return items;
}

// ------------------------------------------------------------- WhatsApp
const WA_LINE = /^\[?(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4}),? (\d{1,2}):(\d{2})(?::\d{2})?(?: ?([ap])\.? ?m\.?)?\]?(?: -)? (.*)$/i;
const WA_CLEAN = /[‎‏‪-‮﻿]/g;
const WA_NOISE = /^<[^>]*>$|(?<![\p{L}\p{N}_])(?:omitted|omitido|omitida|omitidos)(?![\p{L}\p{N}_])|end-to-end|extremo a extremo|\((?:file attached|archivo adjunto)\)|^(?:This message was deleted|You deleted this message|Eliminaste este mensaje|Se eliminó este mensaje|Missed (?:voice|video) call|Llamada perdida)/iu;
const WA_NAME = /(?:WhatsApp Chat (?:with|-)|Chat de WhatsApp con|Conversación de WhatsApp con)\s+(.+)$/i;
const waLine = line => line.replace(WA_CLEAN, '').replace(/[  ]/g, ' ');

export const looksLikeWhatsapp = text =>
  text.slice(0, 4000).split(/\r?\n/).slice(0, 25).filter(l => WA_LINE.test(waLine(l))).length >= 3;

export function readWhatsapp(text, name, key) {
  const raw = [];
  for (const line of text.split(/\r?\n/)) {
    const m = WA_LINE.exec(waLine(line));
    if (m) raw.push(m.slice(1));
    else if (raw.length) raw[raw.length - 1][6] += '\n' + waLine(line);
  }
  const dayFirst = !raw.some(r => +r[1] > 12) || raw.some(r => +r[0] > 12);  // 03/04 is ambiguous: ask the whole file
  const rows = [];
  for (const [a, b, y, hh, mm, ap, rest] of raw) {
    const at = rest.indexOf(': ');
    if (at < 0) continue;  // system line
    const [d, mo] = dayFirst ? [+a, +b] : [+b, +a];
    let hour = +hh % 24;
    if (ap) hour = hour % 12 + (ap.toLowerCase() === 'p' ? 12 : 0);
    const when = new Date(+y + (y.length <= 2 ? 2000 : 0), mo - 1, d, hour, +mm);  // phone time = local time
    if (Number.isNaN(when.getTime()) || when.getDate() !== d) continue;
    const body = rest.slice(at + 2).replace(/<[^>]*(?:edited|editó)[^>]*>/g, '').trim();
    if (body && !WA_NOISE.test(body)) rows.push([when.getTime(), rest.slice(0, at).trim(), body]);
  }
  return { name, key, rows };
}

/** Who is "you" in these chats? Lower-cased names; empty if it cannot be told. */
export function whatsappMe(chats, names) {
  if (names.size) return names;
  const seen = new Map();
  for (const chat of chats) for (const s of new Set(chat.rows.map(r => r[1].toLowerCase()))) seen.set(s, (seen.get(s) || 0) + 1);
  if (chats.length >= 2 && seen.size) {  // you are the one who is in every chat
    const inAll = [...seen].filter(([, n]) => n === chats.length);
    if (inAll.length === 1) return new Set([inAll[0][0]]);
  }
  const found = new Set();
  for (const chat of chats) {  // a 1:1 chat is named after the other person
    const senders = new Set(chat.rows.map(r => r[1].toLowerCase())), other = chat.name.toLowerCase();
    if (senders.size === 2 && senders.has(other)) for (const s of senders) if (s !== other) found.add(s);
  }
  return found.size === 1 ? found : new Set();
}

const localDay = ms => { const d = new Date(ms); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

/** One item per chat and day, holding only the messages you sent. */
export function whatsappItems(chats, me) {
  const items = [];
  for (const chat of chats) {
    const days = new Map();
    for (const [when, sender, body] of chat.rows) {
      const key = localDay(when);
      if (!days.has(key)) days.set(key, { mine: [], total: 0 });
      const day = days.get(key);
      day.total++;
      if (me.has(sender.toLowerCase())) day.mine.push([when, body.replace(/https?:\/\/\S+/g, ' ')]);
    }
    for (const [date, day] of days) {
      const text = day.mine.map(m => m[1]).join('\n').trim();
      if (countWords(text) < WA_MIN_WORDS) continue;
      items.push(item(`whatsapp:${chat.key}:${date}`, chat.name || 'WhatsApp', day.mine[0][0], 'whatsapp', 'message',
        text.slice(0, MAX_NOTE), { parts: day.mine.map(m => m[0]), size: day.total }));
    }
  }
  return items;
}

// ------------------------------------------------------------ documents
async function parseDocx(file, rel, ctx) {
  let entries;
  try { entries = await listZip(file.blob || new Blob([await file.bytes()]), { note: ctx.note, archive: file.path }); } catch { return null; }
  const doc = entries.find(e => e.path === 'word/document.xml');
  if (!doc) return null;
  const xml = await doc.text();
  const core = entries.find(e => e.path === 'docProps/core.xml');
  const coreXml = core ? await core.text() : '';
  const paragraphs = [];
  for (const m of xml.matchAll(/<w:p[ >][\s\S]*?<\/w:p>/g)) {
    const para = m[0].replace(/<w:(?:tab|br|cr)\b[^>]*\/>/g, ' ');
    const text = unescapeHtml([...para.matchAll(/<w:t(?:\s[^>]*)?>([^<]*)<\/w:t>/g)].map(t => t[1]).join('')).trim();
    if (text) paragraphs.push(text);
  }
  const text = squash(paragraphs.join(' ').replace(/https?:\/\/\S+/g, ' '));
  if (countWords(text) < 3) return null;
  const title = /<dc:title>([^<]+)<\/dc:title>/.exec(coreXml);
  const stamp = tag => {
    const m = new RegExp(`<dcterms:${tag}[^>]*>([^<]+)</dcterms:${tag}>`).exec(coreXml);
    return m ? realDate(m[1]) : null;
  };
  return item(`word:${rel}`, (title ? unescapeHtml(title[1]).trim() : '') || stem(file.path),
    stamp('created') ?? stamp('modified') ?? file.mtime, 'word', 'note', text.slice(0, MAX_NOTE));
}

async function parsePdf(file, rel, ctx) {
  if (!ctx.pdfText) { ctx.note('PDF files were skipped: this build cannot read them.'); return null; }
  let got;
  try { got = await ctx.pdfText(await file.bytes(), baseName(file.path)); } catch (err) { ctx.note(`PDF: could not read ${baseName(file.path)} (${(err && err.message) || err})`); return null; }
  const text = squash((got && got.text || '').replace(/https?:\/\/\S+/g, ' '));
  if (countWords(text) < 3) return null;  // scanned pages have no text layer
  return item(`pdf:${rel}`, (got.title || '').trim() || stem(file.path), realDate(got.created) ?? file.mtime, 'pdf', 'note', text.slice(0, MAX_NOTE));
}

// ------------------------------------------------- files, folders and ZIPs
const wantedJson = rel => {
  const low = rel.toLowerCase(), name = baseName(low);
  return name === 'conversations.json' || name.includes('brainplug') || ((low.includes('gemini') || low.includes('bard')) && name.includes('activ'));
};
const wantedHtml = rel => { const low = rel.toLowerCase(); return low.includes('gemini') && low.includes('activ'); };
const hiddenPath = rel => rel.split('/').some(p => p.startsWith('.') || SKIP_DIRS.has(p));

async function loadFile(file, rel, ctx, { noteSource = 'notes', inside = false, hint = '' } = {}) {
  const ext = suffix(file.path);
  ctx.progress('file', rel);
  if (ext === '.json') {
    if (inside && !wantedJson(rel)) return [];
    try { return parseJson(JSON.parse(await file.text())); } catch (err) { if (inside) return []; throw err instanceof SyntaxError ? new Error(`${baseName(file.path)} is not valid JSON.`) : err; }
  }
  if (ext === '.html') return !inside || wantedHtml(rel) ? parseGeminiHtml(await file.text()) : [];
  if (ext === '.mbox') return loadGmail(file, ctx.emails, ctx.note);
  if (ext === '.jsonl') {  // a Claude Code or Codex session
    const session = parseSession(await file.text(60000000), stem(file.path));
    return session ? [session] : [];
  }
  if (ext === '.zip') return loadZip(file, ctx);
  if (ext === '.docx') {
    try {
      const doc = baseName(file.path).startsWith('~$') ? null : await parseDocx(file, rel, ctx);
      return doc ? [doc] : [];
    } catch (err) { if (!(err instanceof ZipSkip)) throw err; return []; }
  }
  if (ext === '.pdf') {
    if (inside && !ctx.pdf) return [];  // PDFs in a folder are usually other people's writing
    const doc = await parsePdf(file, rel, ctx);
    return doc ? [doc] : [];
  }
  if (NOTE_SUFFIXES.has(ext)) {
    const text = await file.text(ext === '.txt' ? 60000000 : MAX_NOTE);
    if (ext === '.txt' && looksLikeWhatsapp(text)) {
      const m = WA_NAME.exec(stem(file.path)) || WA_NAME.exec(hint);
      const name = (m ? m[1].trim() : '') || (stem(file.path) === '_chat' ? hint : stem(file.path));
      ctx.chats.push(readWhatsapp(text, name, name || rel));
      return [];
    }
    if (TOPIC_NAMES.test(rel)) {  // names the person gave topics, matched by their words
      for (const line of text.split(/\r?\n/)) {
        const m = NAME_LINE.exec(line);
        if (m) ctx.topicNames.push([m[1].trim(), m[2].split(',').map(w => w.trim().toLowerCase()).filter(Boolean)]);
      }
      return [];
    }
    if (EXCLUDED.test(rel)) {  // what the person asked to leave out of the brain
      const vault = rel.slice(0, rel.length - 'Brainplug/Excluded.md'.length);  // "" or "Vault/"
      for (const line of text.split(/\r?\n/)) {
        const m = EXCLUDED_LINE.exec(line);
        if (!m) continue;
        const id = m[2].trim(), at = id.indexOf(':');
        if (m[1]) ctx.excludedSources.add(id);
        else {
          ctx.excludedIds.add(id);
          if (vault && at > 0) ctx.excludedIds.add(`${id.slice(0, at)}:${vault}${id.slice(at + 1)}`);
        }
      }
      return [];
    }
    if (GENERATED.test(rel)) return [];
    const note = ext !== '.txt' && NOTION_ID.test(stem(file.path))
      ? parseNotionPage(text, file.path, rel, file.mtime) : parseNote(text, file.path, rel, MEMORY.test(rel) ? 'memory' : noteSource, file.mtime);
    return note ? [note] : [];
  }
  return [];
}

async function loadFolder(files, ctx, hint = '') {
  const isVault = files.some(f => ('/' + f.path).includes('/.obsidian/'));
  const out = [];
  for (const file of [...files].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))) {
    if (hiddenPath(file.path)) continue;
    try {
      out.push(...await loadFile(file, file.path, ctx, { noteSource: isVault ? 'obsidian' : 'notes', inside: true, hint }));
    } catch (err) { if (!(err instanceof ZipSkip)) throw err; }
  }
  return out;
}

async function loadZip(file, ctx) {
  const depth = (ctx.zipDepth || 0) + 1;
  if (depth > ZIP_LIMITS.depth) { ctx.note(`ZIP: skipped ${file.path} (nesting depth limit).`); return []; }
  const state = ctx.zipState || { entries: 0, bytes: 0 };
  try {
    const blob = file.blob || new Blob([await file.bytes()]);
    const keep = new Set([...NOTE_SUFFIXES, '.mbox', '.zip', '.docx', '.pdf', '.json', '.html']);
    const wanted = name => keep.has(suffix(name)) && (suffix(name) !== '.json' || wantedJson(name))
      && (suffix(name) !== '.html' || wantedHtml(name));
    const all = await listZip(blob, { note: ctx.note, state, archive: file.path, wanted });
    return await loadFolder(all, { ...ctx, zipDepth: depth, zipState: state }, stem(file.path));
  } catch (err) { if (!(err instanceof ZipSkip)) throw err; return []; }
}

/**
 * Load any mix of exports, folders and ZIPs. Oldest item first.
 * inputs: [{ path, blob, mtime?, inside? }]  (inside = it came from a dropped folder; path is relative to that folder's parent)
 * options: { me: [emails and names], pdf: bool, pdfText: async (bytes, name) => ({text, title, created}), progress, note }
 */
export async function load(inputs, options = {}) {
  const me = (options.me || []).map(m => m.trim()).filter(Boolean);
  const notes = [];
  const ctx = {
    emails: me.filter(m => m.includes('@')), names: new Set(me.filter(m => !m.includes('@')).map(m => m.toLowerCase())),
    pdf: !!options.pdf, pdfText: options.pdfText, chats: [],
    progress: options.progress || (() => {}), note: text => { if (!notes.includes(text)) notes.push(text); },
    excludedIds: new Set(), excludedSources: new Set(), topicNames: [],
  };
  const found = [];
  const folders = new Map();
  for (const input of inputs) {
    const file = input.chunks ? input : blobFile(input.path, input.blob, input.mtime);
    if (input.inside) {  // group dropped folders by their top-level name
      const at = file.path.indexOf('/');
      const top = at < 0 ? '' : file.path.slice(0, at);
      if (!folders.has(top)) folders.set(top, []);
      folders.get(top).push(Object.assign(Object.create(file), { path: at < 0 ? file.path : file.path.slice(at + 1) }));
    } else found.push(...await loadFile(file, baseName(file.path), ctx));
  }
  for (const [top, files] of folders) found.push(...await loadFolder(files, ctx, top));
  if (ctx.chats.length) {
    const who = whatsappMe(ctx.chats, ctx.names);
    if (who.size) {
      if (!ctx.names.size) {
        const row = ctx.chats.flatMap(c => c.rows).find(r => who.has(r[1].toLowerCase()));
        const sender = row ? row[1] : [...who].sort()[0];
        const evidence = ctx.chats.length === 1 ? 'the file name' : `${ctx.chats.length} chats`;
        ctx.note(`WhatsApp: kept the messages written by ${sender} (detected from ${evidence}; to change it, give your name in “Who you are” or with --me).`);
      }
      found.push(...whatsappItems(ctx.chats, who));
    } else {
      const senders = [...new Set(ctx.chats.flatMap(c => c.rows.map(r => r[1])))].sort().slice(0, 6);
      ctx.note(`WhatsApp: unsure: could not tell which sender is you, so those chats were skipped. Give your name as it appears in the chat in “Who you are” or with --me (seen: ${senders.join(', ')}).`);
    }
  }
  const items = new Map();
  for (const it of found) {
    const old = items.get(it.id);
    if (!old) items.set(it.id, it);
    else if (old.text === it.text) continue;  // the same thing reached twice, e.g. a folder given twice
    else if (old.msgs && old.msgs.length && it.msgs && it.msgs.length) items.set(it.id, mergeChats(old, it));  // an export and a later live capture
    else if (it.kind === 'note') {  // a different note at the same place in another folder: keep both
      let n = 2;
      while (items.has(`${it.id}#${n}`)) n++;
      it.id = `${it.id}#${n}`;
      items.set(it.id, it);
    } else if (it.words > old.words) items.set(it.id, it);  // an older and a newer export of the same thread
  }
  const kept = [...items.values()].filter(it => !ctx.excludedIds.has(it.id) && !ctx.excludedSources.has(it.source));
  return { items: kept.sort((a, b) => a.created - b.created), notes, topicNames: ctx.topicNames };
}

const same = text => text.split(/\s+/).filter(Boolean).join(' ');

// One conversation found in two places (an export and the extension's capture made after it):
// keep every message once. A message both have is counted once per copy.
export function mergeChats(a, b) {
  const [base, other] = a.msgs.length >= b.msgs.length ? [a, b] : [b, a];
  const unmatched = new Map();
  for (const m of base.msgs) unmatched.set(same(m), (unmatched.get(same(m)) || 0) + 1);
  const extra = [];
  other.msgs.forEach((text, i) => {
    const left = unmatched.get(same(text)) || 0;
    if (left) unmatched.set(same(text), left - 1);
    else extra.push([other.parts[i], text]);
  });
  if (!extra.length) return base;
  const rows = [...base.parts.map((w, i) => [w, base.msgs[i]]), ...extra].sort((x, y) => x[0] - y[0]);
  const text = rows.map(r => r[1]).join('\n');
  return { ...base, title: base.title && base.title !== 'Untitled' ? base.title : other.title,
    created: Math.min(base.created, other.created), text, words: countWords(text),
    parts: rows.map(r => r[0]), msgs: rows.map(r => r[1]), size: base.size + 2 * extra.length };
}

export { blobFile, bytesFile };
