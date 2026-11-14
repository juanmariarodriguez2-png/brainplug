// Exercise loader notes without needing enough items for an analysis.
import fs from 'node:fs';
import path from 'node:path';
import { load } from '../../docs/app/engine/sources.js';

const [me, ...files] = process.argv.slice(2);
const inputs = await Promise.all(files.map(async file => ({
  path: path.basename(file), blob: await fs.openAsBlob(file),
})));
const { items, notes } = await load(inputs, { me: JSON.parse(me) });
console.log(JSON.stringify({ count: items.length, notes, text: items.map(i => i.text).join('\n') }));
