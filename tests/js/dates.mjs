// Print the title and date (ms since 1970) the browser engine gives each file, with the file's own date.
import fs from 'node:fs';
import path from 'node:path';
import { load } from '../../docs/app/engine/sources.js';

const inputs = await Promise.all(process.argv.slice(2).map(async file => ({
  path: path.basename(file), blob: await fs.openAsBlob(file), mtime: fs.statSync(file).mtimeMs,
})));
const { items } = await load(inputs, {});
console.log(JSON.stringify(items.map(it => [it.title, it.created])));
