// Run the browser engine in Node on a folder of inputs, the way the web page would:
//   node tests/js/run_engine.mjs <folder> <out.json> [--topics N] [--pdf] [--private] [--html]
// Files at the top level are "dropped" one by one; each sub-folder is dropped as a folder.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const { build, renderHtml } = await import(pathToFileURL(path.join(here, '../../docs/app/engine/index.js')));

const [folder, out, ...rest] = process.argv.slice(2);
const topics = rest.includes('--topics') ? +rest[rest.indexOf('--topics') + 1] : null;
const inputs = [];
async function add(file, rel, inside) {
  inputs.push({ path: rel, blob: await fs.openAsBlob(file), mtime: fs.statSync(file).mtimeMs, inside });
}
async function walk(dir, rel) {
  for (const name of fs.readdirSync(dir).sort()) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) await walk(full, `${rel}/${name}`);
    else await add(full, `${rel}/${name}`, true);
  }
}
for (const name of fs.readdirSync(folder).sort()) {
  const full = path.join(folder, name);
  if (fs.statSync(full).isDirectory()) await walk(full, name);
  else if (!name.endsWith('.pdf') || rest.includes('--pdf')) await add(full, name, false);
}
const started = Date.now();
const { payload, notes } = await build(inputs, { topics, title: 'Parity', me: [], private: rest.includes('--private') });
if (rest.includes('--html')) {
  const tpl = fs.readFileSync(path.join(here, '../../docs/app/viewer.tpl.html'), 'utf8');
  fs.writeFileSync(out.replace(/\.json$/, '.html'), renderHtml(tpl, payload, 'es'));
}
fs.writeFileSync(out, JSON.stringify(payload));
console.log(JSON.stringify({ items: payload.numbers.items, topics: payload.topics.length, notes, ms: Date.now() - started }));
