// Read ZIP files without loading them whole: the central directory tells where
// each entry is, so only the entries Brainprint needs are ever read (the photos
// and videos in an export are skipped). Works on a File/Blob, in the browser and in Node.
import { Inflate } from '../vendor/fflate.js';

const u16 = (b, o) => b[o] | (b[o + 1] << 8);
const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
const u64 = (b, o) => u32(b, o) + u32(b, o + 4) * 4294967296;
const utf8 = new TextDecoder('utf-8');
export const STEP = 8 << 20;

export async function slice(blob, start, end) {
  return new Uint8Array(await blob.slice(start, end).arrayBuffer());
}

export function concat(parts) {
  if (parts.length === 1) return parts[0];
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

/** A file-like object every loader understands. */
function makeFile(path, size, mtime, chunks, blob = null) {
  return {
    path, size, mtime, blob, chunks,
    async bytes() { const parts = []; for await (const c of chunks()) parts.push(c); return concat(parts.length ? parts : [new Uint8Array(0)]); },
    async text(limit = Infinity) {
      const parts = []; let n = 0;
      for await (const c of chunks()) { parts.push(c); n += c.length; if (n >= limit) break; }
      return utf8.decode(concat(parts.length ? parts : [new Uint8Array(0)]).subarray(0, limit));
    },
  };
}

export function blobFile(path, blob, mtime = blob.lastModified || Date.now()) {
  return makeFile(path, blob.size, mtime, async function* () {
    for (let o = 0; o < blob.size; o += STEP) yield await slice(blob, o, Math.min(blob.size, o + STEP));
  }, blob);
}

export function bytesFile(path, bytes, mtime = Date.now()) {
  return makeFile(path, bytes.length, mtime, async function* () { yield bytes; }, new Blob([bytes]));
}

/** List the entries of a ZIP (zip64 included) as file-like objects. */
export async function listZip(blob) {
  const size = blob.size;
  const tail = await slice(blob, Math.max(0, size - 65557 - 20), size);
  let e = tail.length - 22;
  while (e >= 0 && u32(tail, e) !== 0x06054b50) e--;
  if (e < 0) throw new Error('Not a ZIP file');
  let total = u16(tail, e + 10), cdSize = u32(tail, e + 12), cdOffset = u32(tail, e + 16);
  if (total === 0xffff || cdSize === 0xffffffff || cdOffset === 0xffffffff) {
    const loc = e - 20;
    if (loc < 0 || u32(tail, loc) !== 0x07064b50) throw new Error('Damaged ZIP file');
    const at = u64(tail, loc + 8);
    const rec = await slice(blob, at, at + 56);
    if (u32(rec, 0) !== 0x06064b50) throw new Error('Damaged ZIP file');
    total = u64(rec, 32); cdSize = u64(rec, 40); cdOffset = u64(rec, 48);
  }
  const cd = await slice(blob, cdOffset, cdOffset + cdSize);
  const out = [];
  for (let p = 0, i = 0; i < total && p + 46 <= cd.length && u32(cd, p) === 0x02014b50; i++) {
    const method = u16(cd, p + 10), time = u16(cd, p + 12), date = u16(cd, p + 14);
    let csize = u32(cd, p + 20), usize = u32(cd, p + 24), offset = u32(cd, p + 42);
    const nlen = u16(cd, p + 28), xlen = u16(cd, p + 30), clen = u16(cd, p + 32);
    const name = utf8.decode(cd.subarray(p + 46, p + 46 + nlen));
    for (let x = p + 46 + nlen, end = x + xlen; x + 4 <= end;) {  // zip64 sizes live in an extra field
      const id = u16(cd, x), len = u16(cd, x + 2);
      if (id === 1) {
        let q = x + 4;
        if (usize === 0xffffffff) { usize = u64(cd, q); q += 8; }
        if (csize === 0xffffffff) { csize = u64(cd, q); q += 8; }
        if (offset === 0xffffffff) offset = u64(cd, q);
      }
      x += 4 + len;
    }
    p += 46 + nlen + xlen + clen;
    if (name.endsWith('/')) continue;
    const mtime = new Date(((date >> 9) & 0x7f) + 1980, ((date >> 5) & 0xf) - 1, date & 0x1f,
      time >> 11, (time >> 5) & 0x3f, (time & 0x1f) * 2).getTime();
    out.push(makeFile(name, usize, Number.isFinite(mtime) ? mtime : Date.now(), async function* () {
      const head = await slice(blob, offset, offset + 30);
      if (u32(head, 0) !== 0x04034b50) throw new Error('Damaged ZIP entry: ' + name);
      const start = offset + 30 + u16(head, 26) + u16(head, 28), stop = start + csize;
      if (method !== 0 && method !== 8) throw new Error('Unsupported ZIP compression in ' + name);
      const ready = [];
      const inflate = method === 8 ? new Inflate((data) => { if (data.length) ready.push(data); }) : null;
      if (csize === 0) return;
      for (let o = start; o < stop; o += STEP) {
        const part = await slice(blob, o, Math.min(stop, o + STEP));
        if (!inflate) { yield part; continue; }
        inflate.push(part, o + STEP >= stop);
        while (ready.length) yield ready.shift();
      }
    }));
  }
  return out;
}
