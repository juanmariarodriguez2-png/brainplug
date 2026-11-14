// Load the same small hostile ZIPs as Python, with reduced limits.
import fs from 'node:fs';
import { ZIP_LIMITS } from '../../docs/app/engine/zip.js';
import { load } from '../../docs/app/engine/sources.js';

const [file, limits] = process.argv.slice(2);
Object.assign(ZIP_LIMITS, JSON.parse(limits));
const input = { path: 'export.zip', blob: await fs.openAsBlob(file) };
const { items, notes } = await load([input, input]); // budgets reset for each top-level ZIP
console.log(JSON.stringify({ count: items.length, notes, text: items.map(i => i.text).join('\n') }));
