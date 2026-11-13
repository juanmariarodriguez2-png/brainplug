// Turn items into topics, connections, two 3D layouts and summary numbers.
// A port of brainprint/analysis.py with no dependencies: TF-IDF, a randomized
// truncated SVD (LSA) and k-means are implemented here so the whole analysis
// runs inside the browser tab.
import * as brain from './brain.js';
import { STOP_WORDS } from './stopwords.js';

export const VERSION = '0.3.0';
const PALETTE = ['#4cc9f0', '#f72585', '#b8f35a', '#ffb703', '#9d4edd', '#2ec4b6', '#ff6b6b', '#ffd6a5', '#80ffdb',
  '#c77dff', '#f15bb5', '#00bbf9', '#fee440', '#a0c4ff', '#ff9f1c', '#06d6a0'];
const KINDS = ['chat', 'note', 'message'];
const SOURCE_NAMES = { chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini', copilot: 'Copilot', perplexity: 'Perplexity',
  obsidian: 'Obsidian', notion: 'Notion', notes: 'Notes', word: 'Word', pdf: 'PDF', gmail: 'Gmail', whatsapp: 'WhatsApp', memory: 'Memory', demo: 'Demo' };
const STOP = new Set(STOP_WORDS);
const WORD = /[\p{L}\p{N}_]+/gu, LETTERS = /^\p{L}{2,}$/u;
const round = (v, d) => { const f = 10 ** d; return Math.round(v * f) / f; };
const pad = n => String(n).padStart(2, '0');
const ymd = ms => { const d = new Date(ms); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const ym = ms => ymd(ms).slice(0, 7);
const stamps = it => (it.parts.length ? it.parts : [it.created]);
const sourceName = s => SOURCE_NAMES[s] || s.charAt(0).toUpperCase() + s.slice(1);
/** Indices sorted by a key, descending, keeping the original order on ties. */
const argsortDesc = (n, key) => Array.from({ length: n }, (_, i) => i).sort((a, b) => key(b) - key(a) || a - b);

// ---------------------------------------------------------------- topics
export function documents(items) {
  // Titles and tags are strong hints, so they count twice. A WhatsApp "title" is a
  // person's name, which says nothing about the topic, so it is left out.
  return items.map(i => (i.source === 'whatsapp' ? i.text.slice(0, 20000)
    : `${i.title}. ${i.title}. ${i.tags.join(' ')} ${i.tags.join(' ')} ${i.text.slice(0, 20000)}`));
}

/** TF-IDF with unigrams and bigrams, like scikit-learn's TfidfVectorizer. Returns a CSR matrix. */
export function vectorize(docs) {
  const n = docs.length;
  const counts = [], df = new Map(), tf = new Map();
  for (const doc of docs) {
    const tokens = [];
    for (const m of doc.toLowerCase().matchAll(WORD)) if (LETTERS.test(m[0]) && !STOP.has(m[0])) tokens.push(m[0]);
    const own = new Map();
    for (let i = 0; i < tokens.length; i++) {
      own.set(tokens[i], (own.get(tokens[i]) || 0) + 1);
      if (i + 1 < tokens.length) { const bi = tokens[i] + ' ' + tokens[i + 1]; own.set(bi, (own.get(bi) || 0) + 1); }
    }
    for (const [term, c] of own) { df.set(term, (df.get(term) || 0) + 1); tf.set(term, (tf.get(term) || 0) + c); }
    counts.push(own);
  }
  const build = (minDf, maxRatio) => {
    const maxCount = maxRatio * n;
    let terms = [];
    for (const [term, d] of df) if (d >= minDf && d <= maxCount) terms.push(term);
    if (!terms.length) return null;
    if (terms.length > 8000) terms = terms.sort((a, b) => tf.get(b) - tf.get(a) || (a < b ? -1 : 1)).slice(0, 8000);
    terms.sort();
    const index = new Map(terms.map((t, i) => [t, i]));
    const idf = terms.map(t => Math.log((1 + n) / (1 + df.get(t))) + 1);
    const indptr = new Int32Array(n + 1), cols = [], vals = [];
    counts.forEach((own, r) => {
      const row = [];
      let norm = 0;
      for (const [term, c] of own) {
        const j = index.get(term);
        if (j === undefined) continue;
        const v = (1 + Math.log(c)) * idf[j];
        row.push([j, v]); norm += v * v;
      }
      norm = Math.sqrt(norm) || 1;
      row.sort((a, b) => a[0] - b[0]);
      for (const [j, v] of row) { cols.push(j); vals.push(v / norm); }
      indptr[r + 1] = cols.length;
    });
    return { vocab: terms, X: { n, m: terms.length, indptr, indices: Int32Array.from(cols), data: Float64Array.from(vals) } };
  };
  // a tiny or very repetitive record keeps every term
  return build(n >= 20 ? 2 : 1, 0.5) || build(1, 1.0) || { vocab: [], X: { n, m: 0, indptr: new Int32Array(n + 1), indices: new Int32Array(0), data: new Float64Array(0) } };
}

// dense helpers: matrices are row-major Float64Array with `cols` columns
function mulX(X, W, cols) {  // X (n×m, sparse) · W (m×cols)
  const out = new Float64Array(X.n * cols);
  for (let i = 0; i < X.n; i++) {
    const o = i * cols;
    for (let p = X.indptr[i]; p < X.indptr[i + 1]; p++) {
      const v = X.data[p], w = X.indices[p] * cols;
      for (let c = 0; c < cols; c++) out[o + c] += v * W[w + c];
    }
  }
  return out;
}
function mulXt(X, Y, cols) {  // Xᵀ (m×n) · Y (n×cols)
  const out = new Float64Array(X.m * cols);
  for (let i = 0; i < X.n; i++) {
    const y = i * cols;
    for (let p = X.indptr[i]; p < X.indptr[i + 1]; p++) {
      const v = X.data[p], o = X.indices[p] * cols;
      for (let c = 0; c < cols; c++) out[o + c] += v * Y[y + c];
    }
  }
  return out;
}
function orthonormalize(A, rows, cols) {  // modified Gram-Schmidt on the columns, in place
  for (let c = 0; c < cols; c++) {
    for (let pass = 0; pass < 2; pass++) {
      for (let b = 0; b < c; b++) {
        let dot = 0;
        for (let r = 0; r < rows; r++) dot += A[r * cols + c] * A[r * cols + b];
        for (let r = 0; r < rows; r++) A[r * cols + c] -= dot * A[r * cols + b];
      }
    }
    let norm = 0;
    for (let r = 0; r < rows; r++) norm += A[r * cols + c] ** 2;
    norm = Math.sqrt(norm);
    const inv = norm > 1e-10 ? 1 / norm : 0;
    for (let r = 0; r < rows; r++) A[r * cols + c] *= inv;
  }
}
/** Eigen-decomposition of a symmetric matrix (cyclic Jacobi). Returns values (descending) and row-major vectors. */
function symmetricEigen(A, n) {
  const V = new Float64Array(n * n);
  for (let i = 0; i < n; i++) V[i * n + i] = 1;
  for (let sweep = 0; sweep < 60; sweep++) {
    let off = 0;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) off += A[i * n + j] ** 2;
    if (off < 1e-22) break;
    for (let p = 0; p < n; p++) {
      for (let q = p + 1; q < n; q++) {
        const apq = A[p * n + q];
        if (Math.abs(apq) < 1e-300) continue;
        const theta = (A[q * n + q] - A[p * n + p]) / (2 * apq);
        const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < n; k++) {
          const akp = A[k * n + p], akq = A[k * n + q];
          A[k * n + p] = c * akp - s * akq; A[k * n + q] = s * akp + c * akq;
        }
        for (let k = 0; k < n; k++) {
          const apk = A[p * n + k], aqk = A[q * n + k];
          A[p * n + k] = c * apk - s * aqk; A[q * n + k] = s * apk + c * aqk;
        }
        for (let k = 0; k < n; k++) {
          const vkp = V[k * n + p], vkq = V[k * n + q];
          V[k * n + p] = c * vkp - s * vkq; V[k * n + q] = s * vkp + c * vkq;
        }
      }
    }
  }
  const order = argsortDesc(n, i => A[i * n + i]);
  return { values: order.map(i => A[i * n + i]), vector: (rank, k) => V[k * n + order[rank]] };
}

/** LSA: project the TF-IDF rows onto their main directions and normalise each row. Returns { Z, d }. */
export function embed(X, seed = 0) {
  const { n, m } = X;
  const d = Math.max(2, Math.min(100, n - 1, m - 1));
  const l = Math.max(1, Math.min(d + 10, n, m));
  const Z = new Float64Array(n * d);
  if (m === 0 || X.data.length === 0) return { Z, d };
  const rng = brain.makeRng(1234 + seed);
  let W = new Float64Array(m * l);
  for (let i = 0; i < W.length; i++) W[i] = rng.normal();
  let Y = mulX(X, W, l);
  for (let it = 0; it < 4; it++) {  // power iterations sharpen the leading directions
    orthonormalize(Y, n, l);
    W = mulXt(X, Y, l);
    orthonormalize(W, m, l);
    Y = mulX(X, W, l);
  }
  orthonormalize(Y, n, l);
  const B = mulXt(X, Y, l);  // m×l, i.e. (Qᵀ X)ᵀ
  const C = new Float64Array(l * l);
  for (let r = 0; r < m; r++) {
    const o = r * l;
    for (let a = 0; a < l; a++) { const v = B[o + a]; if (v !== 0) for (let b = a; b < l; b++) C[a * l + b] += v * B[o + b]; }
  }
  for (let a = 0; a < l; a++) for (let b = 0; b < a; b++) C[a * l + b] = C[b * l + a];
  const eig = symmetricEigen(C, l);
  const use = Math.min(d, l);
  for (let c = 0; c < use; c++) {
    const sigma = Math.sqrt(Math.max(0, eig.values[c]));
    for (let i = 0; i < n; i++) {
      let v = 0;
      for (let k = 0; k < l; k++) v += Y[i * l + k] * eig.vector(c, k);
      Z[i * d + c] = v * sigma;
    }
  }
  for (let i = 0; i < n; i++) {
    let norm = 0;
    for (let c = 0; c < d; c++) norm += Z[i * d + c] ** 2;
    norm = Math.sqrt(norm);
    if (norm > 0) for (let c = 0; c < d; c++) Z[i * d + c] /= norm;
  }
  return { Z, d };
}

function kmeansOnce(Z, n, d, k, rng, maxIter) {
  const centres = new Float64Array(k * d), dist = new Float64Array(n).fill(Infinity);
  const sq = (i, c) => { let s = 0; for (let a = 0; a < d; a++) { const v = Z[i * d + a] - centres[c * d + a]; s += v * v; } return s; };
  const seedCentre = (c, i) => { for (let a = 0; a < d; a++) centres[c * d + a] = Z[i * d + a]; };
  seedCentre(0, rng.int(n));
  const trials = 2 + Math.floor(Math.log(k));
  for (let c = 1; c < k; c++) {  // greedy k-means++: far points are more likely to become centres
    let total = 0;
    for (let i = 0; i < n; i++) { dist[i] = Math.min(dist[i], sq(i, c - 1)); total += dist[i]; }
    let bestAt = 0, bestPot = Infinity;
    for (let t = 0; t < trials; t++) {
      let pick = rng.random() * total, at = n - 1;
      for (let i = 0; i < n; i++) { pick -= dist[i]; if (pick <= 0) { at = i; break; } }
      seedCentre(c, at);
      let pot = 0;
      for (let i = 0; i < n; i++) pot += Math.min(dist[i], sq(i, c));
      if (pot < bestPot) { bestPot = pot; bestAt = at; }
    }
    seedCentre(c, bestAt);
  }
  const labels = new Int32Array(n).fill(-1), norms = new Float64Array(k), sizes = new Int32Array(k);
  let inertia = 0;
  for (let iter = 0; iter < maxIter; iter++) {
    for (let c = 0; c < k; c++) { let s = 0; for (let a = 0; a < d; a++) s += centres[c * d + a] ** 2; norms[c] = s; }
    let changed = 0; inertia = 0;
    for (let i = 0; i < n; i++) {
      let best = 0, bestVal = Infinity, self = 0;
      const o = i * d;
      for (let a = 0; a < d; a++) self += Z[o + a] * Z[o + a];
      for (let c = 0; c < k; c++) {
        let dot = 0;
        const q = c * d;
        for (let a = 0; a < d; a++) dot += Z[o + a] * centres[q + a];
        const val = norms[c] - 2 * dot;
        if (val < bestVal) { bestVal = val; best = c; }
      }
      dist[i] = Math.max(0, bestVal + self); inertia += dist[i];
      if (labels[i] !== best) { labels[i] = best; changed++; }
    }
    if (!changed) break;
    centres.fill(0); sizes.fill(0);
    for (let i = 0; i < n; i++) { const q = labels[i] * d; sizes[labels[i]]++; for (let a = 0; a < d; a++) centres[q + a] += Z[i * d + a]; }
    for (let c = 0; c < k; c++) {
      if (sizes[c]) { for (let a = 0; a < d; a++) centres[c * d + a] /= sizes[c]; continue; }
      let far = 0;  // an empty cluster restarts at the point that fits worst
      for (let i = 1; i < n; i++) if (dist[i] > dist[far]) far = i;
      seedCentre(c, far); dist[far] = 0;
    }
  }
  return { labels, inertia };
}
export function kmeans(Z, n, d, k, rng, nInit = 5, maxIter = 60) {
  let best = null;
  for (let run = 0; run < nInit; run++) {
    const got = kmeansOnce(Z, n, d, k, rng, maxIter);
    if (!best || got.inertia < best.inertia) best = got;
  }
  return best.labels;
}

/** Mean silhouette with cosine distance. Rows are unit vectors, so sums of distances reduce to dot products with cluster sums. */
function silhouette(Z, n, d, labels, k) {
  const sums = new Float64Array(k * d), sizes = new Int32Array(k);
  for (let i = 0; i < n; i++) { sizes[labels[i]]++; for (let a = 0; a < d; a++) sums[labels[i] * d + a] += Z[i * d + a]; }
  let total = 0;
  for (let i = 0; i < n; i++) {
    const own = labels[i];
    if (sizes[own] < 2) continue;
    let a = 0, b = Infinity;
    for (let c = 0; c < k; c++) {
      if (!sizes[c]) continue;
      let dot = 0;
      for (let x = 0; x < d; x++) dot += Z[i * d + x] * sums[c * d + x];
      if (c === own) a = (sizes[c] - dot) / (sizes[c] - 1);
      else b = Math.min(b, 1 - dot / sizes[c]);
    }
    if (b < Infinity) total += (b - a) / Math.max(a, b, 1e-12);
  }
  return total / n;
}

export function chooseK(Z, n, d, seed = 0) {
  if (n < 12) return Math.max(1, Math.min(3, n));
  let S = Z, s = n;
  if (n > 4000) {  // a sample is enough to pick the number of topics
    const rng = brain.makeRng(77 + seed);
    const pick = Array.from({ length: n }, (_, i) => i);
    for (let i = 0; i < 4000; i++) { const j = i + rng.int(n - i); [pick[i], pick[j]] = [pick[j], pick[i]]; }
    s = 4000; S = new Float64Array(s * d);
    for (let i = 0; i < s; i++) S.set(Z.subarray(pick[i] * d, pick[i] * d + d), i * d);
  }
  const lo = 4, hi = Math.min(14, Math.max(5, Math.floor(n / 12)));
  let bestK = lo, bestScore = -1;
  for (let k = lo; k <= hi; k++) {
    const labels = kmeans(S, s, d, k, brain.makeRng(seed + k), 3, 40);
    const score = silhouette(S, s, d, labels, k) + 0.004 * k;  // small bonus so the map is not too coarse
    if (score > bestScore) { bestK = k; bestScore = score; }
  }
  return bestK;
}

const shares = (term, picked) => term.split(' ').some(w => picked.some(p => p.split(' ').includes(w)));

export function labelTopics(X, labels, k, vocab, top = 3) {
  const overall = new Float64Array(X.m), per = Array.from({ length: k }, () => new Float64Array(X.m)), sizes = new Int32Array(k);
  for (let i = 0; i < X.n; i++) {
    sizes[labels[i]]++;
    for (let p = X.indptr[i]; p < X.indptr[i + 1]; p++) { overall[X.indices[p]] += X.data[p]; per[labels[i]][X.indices[p]] += X.data[p]; }
  }
  return per.map((sum, t) => {
    const score = j => sum[j] / Math.max(1, sizes[t]) - 0.5 * overall[j] / X.n;
    const picked = [];
    for (const j of argsortDesc(X.m, score)) {
      if (shares(vocab[j], picked)) continue;  // "pandas" and "pandas groupby" say the same
      picked.push(vocab[j]);
      if (picked.length === top) break;
    }
    return picked;
  });
}

export function itemTerms(X, vocab, top = 4) {
  const out = [];
  for (let i = 0; i < X.n; i++) {
    const a = X.indptr[i], len = X.indptr[i + 1] - a, picked = [];
    for (const j of argsortDesc(len, p => X.data[a + p]).slice(0, top * 2)) {
      const term = vocab[X.indices[a + j]];
      if (!shares(term, picked)) picked.push(term);
      if (picked.length === top) break;
    }
    out.push(picked);
  }
  return out;
}

// ----------------------------------------------------------- connections
/** Edges [i, j, weight, kind]: kind 0 = similar content, 1 = explicit link. */
export function connections(Z, d, items, labels, k, perItem = 3, minSim = 0.5, limit = 8000) {
  const n = items.length, edges = new Map();
  const put = (a, b, w, kind) => {
    const key = Math.min(a, b) * n + Math.max(a, b), old = edges.get(key);
    if (!old || kind > old[3] || (kind === old[3] && w > old[2])) edges.set(key, [Math.min(a, b), Math.max(a, b), w, kind]);
  };
  if (n > 2) {
    const topI = new Int32Array(n * perItem).fill(-1), topS = new Float64Array(n * perItem).fill(-2);
    const offer = (i, j, s) => {
      const o = i * perItem;
      if (s <= topS[o + perItem - 1]) return;
      let p = perItem - 1;
      while (p > 0 && topS[o + p - 1] < s) { topS[o + p] = topS[o + p - 1]; topI[o + p] = topI[o + p - 1]; p--; }
      topS[o + p] = s; topI[o + p] = j;
    };
    const dot = (i, j) => { let s = 0; const a = i * d, b = j * d; for (let x = 0; x < d; x++) s += Z[a + x] * Z[b + x]; return s; };
    if (n <= 6000) {
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) { const s = dot(i, j); if (s >= minSim) { offer(i, j, s); offer(j, i, s); } }
    } else {  // a large record: look for neighbours inside each topic only
      const groups = Array.from({ length: k }, () => []);
      for (let i = 0; i < n; i++) groups[labels[i]].push(i);
      for (const g of groups) for (let a = 0; a < g.length; a++) for (let b = a + 1; b < g.length; b++) { const s = dot(g[a], g[b]); if (s >= minSim) { offer(g[a], g[b], s); offer(g[b], g[a], s); } }
    }
    for (let i = 0; i < n; i++) for (let p = 0; p < perItem; p++) if (topI[i * perItem + p] >= 0) put(i, topI[i * perItem + p], topS[i * perItem + p], 0);
  }
  const byTitle = new Map();
  items.forEach((it, i) => { const key = it.title.trim().toLowerCase(); if (!byTitle.has(key)) byTitle.set(key, i); });
  items.forEach((it, i) => {
    for (const target of it.links) {  // [[wikilinks]] and Notion page links
      const j = byTitle.get(target.trim().toLowerCase());
      if (j !== undefined && j !== i) put(i, j, 1, 1);
    }
  });
  return [...edges.values()].map(([a, b, w, kind]) => [a, b, round(w, 2), kind])
    .sort((x, y) => y[3] - x[3] || y[2] - x[2]).slice(0, limit);
}

/** Pairs of topics joined by items that sit almost as close to another topic's centre as to their own. */
export function topicBridges(Z, d, labels, k, ratio = 0.6, top = 3) {
  if (k < 2) return [];
  const n = labels.length, centres = new Float64Array(k * d), sizes = new Int32Array(k);
  for (let i = 0; i < n; i++) { sizes[labels[i]]++; for (let a = 0; a < d; a++) centres[labels[i] * d + a] += Z[i * d + a]; }
  for (let c = 0; c < k; c++) {
    let norm = 0;
    for (let a = 0; a < d; a++) norm += centres[c * d + a] ** 2;
    norm = Math.sqrt(norm) || 1;
    for (let a = 0; a < d; a++) centres[c * d + a] /= norm;
  }
  const pairs = new Map();
  for (let i = 0; i < n; i++) {
    let own = 0, second = -1, s2 = -Infinity;
    for (let c = 0; c < k; c++) {
      let dot = 0;
      for (let a = 0; a < d; a++) dot += Z[i * d + a] * centres[c * d + a];
      if (c === labels[i]) own = dot; else if (dot > s2) { s2 = dot; second = c; }
    }
    if (s2 >= ratio * own && s2 > 0.2) {
      const a = Math.min(labels[i], second), b = Math.max(labels[i], second), key = a * k + b;
      if (!pairs.has(key)) pairs.set(key, { a, b, n: 0, ex: [] });
      const pair = pairs.get(key);
      pair.n++; pair.ex.push([s2, i]);
    }
  }
  return [...pairs.values()].sort((x, y) => y.n - x.n).slice(0, top)
    .map(p => ({ a: p.a, b: p.b, n: p.n, ex: p.ex.sort((x, y) => y[0] - x[0] || y[1] - x[1]).slice(0, 3).map(e => e[1]) }));
}

// --------------------------------------------------------------- numbers
function longestStreak(days) {
  let best = 0, cur = 0, prev = null;
  for (const day of [...days].sort((a, b) => a - b)) {
    cur = prev !== null && day - prev === 1 ? cur + 1 : 1;
    best = Math.max(best, cur); prev = day;
  }
  return best;
}
const dayNumber = ms => { const d = new Date(ms); return Math.round(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86400000); };

export function summary(items, dated, isPrivate) {
  const timed = items.filter((_, i) => dated[i]);
  const all = timed.flatMap(stamps);
  const heat = Array.from({ length: 7 }, () => new Array(24).fill(0));
  for (const s of all) { const d = new Date(s); heat[(d.getDay() + 6) % 7][d.getHours()]++; }
  const months = new Map();
  for (const it of timed) months.set(ym(it.created), (months.get(ym(it.created)) || 0) + 1);
  const busiest = [...months].reduce((best, cur) => (cur[1] > best[1] ? cur : best));
  const days = new Set(all.map(dayNumber));
  const longest = items.reduce((best, it) => (it.words > best.words ? it : best));
  const bySource = new Map();
  for (const it of items) {
    if (!bySource.has(it.source)) bySource.set(it.source, { id: it.source, name: sourceName(it.source), count: 0, words: 0 });
    const s = bySource.get(it.source);
    s.count++; s.words += it.words;
  }
  const rowSum = heat.map(r => r.reduce((a, b) => a + b, 0));
  const colSum = Array.from({ length: 24 }, (_, h) => heat.reduce((a, r) => a + r[h], 0));
  const argmax = arr => arr.indexOf(Math.max(...arr));
  const night = heat.reduce((a, r) => a + r.slice(0, 6).reduce((x, y) => x + y, 0), 0);
  return {
    items: items.length,
    kinds: Object.fromEntries(KINDS.map(kind => [kind, items.filter(it => it.kind === kind).length])),
    writes: all.length,
    words: items.reduce((a, it) => a + it.words, 0),
    first: ymd(Math.min(...timed.map(it => it.created))),
    last: ymd(Math.max(...timed.map(it => it.created))),
    active_days: days.size,
    streak: longestStreak(days),
    busiest_month: { month: busiest[0], count: busiest[1] },
    busiest_weekday: argmax(rowSum),
    busiest_hour: argmax(colSum),
    night_share: round(night / Math.max(1, all.length), 3),
    longest: { title: isPrivate ? null : longest.title, words: longest.words },
    sources: [...bySource.values()].sort((a, b) => b.count - a.count),
    undated: dated.filter(ok => !ok).length,
    heat,
  };
}

function monthRange(first, last) {
  const a = new Date(first), b = new Date(last), out = [];
  for (let y = a.getFullYear(), m = a.getMonth(); y < b.getFullYear() || (y === b.getFullYear() && m <= b.getMonth()); m === 11 ? (y++, m = 0) : m++) out.push(`${y}-${pad(m + 1)}`);
  return out;
}

// --------------------------------------------------------------- review
export function review(items, labels, dated, k, edges, bridges, windowDays = 60) {
  const idx = items.map((_, i) => i).filter(i => dated[i]);
  const last = Math.max(...idx.map(i => items[i].created)), win = windowDays * 86400000, DAY = 86400000;
  const recent = new Array(k).fill(0), before = new Array(k).fill(0), sizes = new Array(k).fill(0);
  const firstSeen = new Array(k).fill(null), lastSeen = new Array(k).fill(null);
  labels.forEach(t => { sizes[t]++; });
  for (const i of idx) {
    const c = items[i].created, t = labels[i];
    if (c > last - win) recent[t]++; else if (c > last - 2 * win) before[t]++;
    firstSeen[t] = firstSeen[t] === null ? c : Math.min(firstSeen[t], c);
    lastSeen[t] = lastSeen[t] === null ? c : Math.max(lastSeen[t], c);
  }
  const delta = recent.map((r, t) => r - before[t]);
  const row = t => ({ k: t, now: recent[t], before: before[t] });
  const rising = argsortDesc(k, t => delta[t]).filter(t => delta[t] > 0).slice(0, 3).map(row);
  const fading = argsortDesc(k, t => -delta[t]).filter(t => delta[t] < 0).slice(0, 3).map(row);
  const dormant = [];
  for (let t = 0; t < k; t++) {
    if (lastSeen[t] !== null && Math.floor((last - lastSeen[t]) / DAY) >= 90) dormant.push({ k: t, days: Math.floor((last - lastSeen[t]) / DAY), last: ymd(lastSeen[t]) });
  }
  dormant.sort((a, b) => sizes[b.k] - sizes[a.k]);
  const seen = firstSeen.map((v, t) => t).filter(t => firstSeen[t] !== null);
  let newest = null;
  if (seen.length) {
    const t = seen.reduce((best, cur) => (firstSeen[cur] > firstSeen[best] ? cur : best));
    if (Math.floor((last - firstSeen[t]) / DAY) <= 150 && firstSeen[t] > Math.min(...seen.map(s => firstSeen[s]))) newest = { k: t, since: ym(firstSeen[t]) };
  }
  // connections between different apps; the most telling ones join different kinds of writing
  const cross = edges.filter(([a, b]) => items[a].source !== items[b].source)
    .map(([a, b, w]) => [items[a].kind !== items[b].kind ? 1 : 0, w, a, b])
    .sort((x, y) => y[0] - x[0] || y[1] - x[1] || y[2] - x[2] || y[3] - x[3]);
  const picked = [], shown = new Set();
  for (const [, , a, b] of cross) {
    if (!shown.has(a) && !shown.has(b)) { picked.push([a, b]); shown.add(a); shown.add(b); }
    if (picked.length === 6) break;
  }
  const end = new Date(last), target = `${end.getFullYear() - 1}-${pad(end.getMonth() + 1)}`;
  return {
    window: windowDays, rising, fading, dormant: dormant.slice(0, 3), newest, bridges,
    cross: picked, cross_total: cross.length,
    deep: argsortDesc(items.length, i => items[i].words).slice(0, 5),
    year_ago: idx.filter(i => ym(items[i].created) === target).slice(0, 8),
  };
}

/** First three principal components of some rows of Z, each scaled to -1..1. */
function localShape(Z, d, idx) {
  const mean = new Float64Array(d), m = idx.length;
  for (const i of idx) for (let a = 0; a < d; a++) mean[a] += Z[i * d + a] / m;
  const cov = new Float64Array(d * d), row = new Float64Array(d);
  for (const i of idx) {
    for (let a = 0; a < d; a++) row[a] = Z[i * d + a] - mean[a];
    for (let a = 0; a < d; a++) { const v = row[a]; if (v !== 0) for (let b = a; b < d; b++) cov[a * d + b] += v * row[b]; }
  }
  for (let a = 0; a < d; a++) for (let b = 0; b < a; b++) cov[a * d + b] = cov[b * d + a];
  const eig = symmetricEigen(cov, d);
  const out = idx.map(i => [0, 1, 2].map(c => {
    let v = 0;
    for (let a = 0; a < d; a++) v += (Z[i * d + a] - mean[a]) * eig.vector(c, a);
    return v;
  }));
  for (let c = 0; c < 3; c++) {
    const max = Math.max(...out.map(p => Math.abs(p[c]))) + 1e-9;
    for (const p of out) p[c] /= max;
  }
  return out;
}

// ------------------------------------------------------------ main entry
/**
 * items: from sources.load(). options: { topics, private, rename: {index: name}, title, seed, progress }.
 * Returns the same payload as brainprint.analysis.analyse(), ready for the viewer.
 */
export function analyse(items, options = {}) {
  const { topics: nTopics = null, private: isPrivate = false, rename = {}, title = 'My Brainprint', seed = 0, progress = () => {} } = options;
  if (items.length < 3) throw new Error('Need at least 3 items (chats, notes, documents or messages) to build a brainprint.');
  const rng = brain.makeRng(seed), n = items.length;
  let dated = items.map(it => it.dated);
  if (!dated.some(Boolean)) dated = dated.map(() => true);  // nothing carries a real date: fall back to file dates

  progress('words');
  const { vocab, X } = vectorize(documents(items));
  progress('directions');
  const { Z, d } = embed(X, seed);
  progress('topics');
  let k = Math.max(1, Math.min(nTopics || chooseK(Z, n, d, seed), PALETTE.length, n));
  const raw = kmeans(Z, n, d, k, brain.makeRng(seed + 99), n > 10000 ? 3 : n > 3000 ? 5 : 10);
  const used = [...new Set(raw)].sort((a, b) => a - b);  // drop clusters that ended up empty
  k = used.length;
  const counts = new Array(k).fill(0);
  raw.forEach(l => { counts[used.indexOf(l)]++; });
  const order = argsortDesc(k, t => counts[t]);  // biggest topic first
  const remap = new Array(k);
  order.forEach((old, rank) => { remap[old] = rank; });
  const labels = Array.from(raw, l => remap[used.indexOf(l)]);
  const sizes = order.map(t => counts[t]);

  const terms = labelTopics(X, labels, k, vocab);
  const topics = terms.map((t, i) => ({
    id: i, name: rename[i] || (t.length ? t.slice(0, 2).join(' · ') : `Topic ${i + 1}`), terms: t,
    color: PALETTE[i], count: sizes[i], share: round(sizes[i] / n, 3),
  }));
  progress('connections');
  const edges = connections(Z, d, items, labels, k);

  // time, normalised to 0..1
  const timed = items.filter((_, i) => dated[i]).map(it => it.created);
  const t0 = Math.min(...timed), t1 = Math.max(...timed), span = Math.max(1000, t1 - t0);
  const when = items.map((it, i) => (dated[i] ? Math.min(1, Math.max(0, (it.created - t0) / span)) : 0));

  progress('layout');
  const pos = new Array(n);
  const anchor = brain.anchors(k, 11 + seed), maxSize = Math.max(...sizes);
  for (let t = 0; t < k; t++) {
    const idx = [];
    labels.forEach((l, i) => { if (l === t) idx.push(i); });
    const local = idx.length >= 4 ? localShape(Z, d, idx) : idx.map(() => [rng.normal(0.5), rng.normal(0.5), rng.normal(0.5)]);
    const placed = brain.placeCluster(anchor[t], local, 0.16 + 0.22 * Math.sqrt(idx.length / maxSize), rng);
    idx.forEach((i, j) => { pos[i] = placed[j]; });
  }
  const gal = brain.galaxy(labels, when.map((w, i) => (dated[i] ? w : rng.random())), k, rng);

  const maxWords = Math.max(...items.map(it => it.words));
  const points = items.map((it, i) => [
    ...pos[i].map(v => round(v, 3)), ...gal[i].map(v => round(v, 3)), labels[i],
    round(0.7 + 1.6 * Math.log1p(it.words) / Math.log1p(maxWords), 2), round(when[i], 4), KINDS.indexOf(it.kind),
  ]);
  const own = isPrivate ? null : itemTerms(X, vocab);
  const itemsOut = items.map((it, i) => ({
    t: isPrivate ? null : it.title, d: ymd(it.created), h: new Date(it.created).getHours(),
    n: it.size, p: stamps(it).length, w: it.words, k: labels[i], s: it.source,
    x: isPrivate ? null : it.text.split(/\s+/).filter(Boolean).join(' ').slice(0, 180),
    tm: own ? own[i] : null, u: dated[i] ? 0 : 1,
  }));

  // spine / core: every message you wrote, oldest first
  let rows = [];
  items.forEach((it, i) => { if (dated[i]) for (const s of stamps(it)) rows.push([s, labels[i]]); });
  rows.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (rows.length > 3000) rows = Array.from({ length: 3000 }, (_, j) => rows[Math.floor(j * rows.length / 3000)]);
  const along = rows.map((_, j) => (rows.length > 1 ? 0.02 + 0.96 * j / (rows.length - 1) : 0.02));
  const spineXyz = brain.spinePoints(rows.length, rng, 0.85, along);
  const spineT = rows.map(r => Math.min(1, Math.max(0, (r[0] - t0) / span)));
  const core = brain.galaxyCore(spineT, rng);
  const spine = rows.map((r, j) => [...spineXyz[j].map(v => round(v, 3)), ...core[j].map(v => round(v, 3)), r[1], round(spineT[j], 4)]);

  const months = monthRange(t0, t1), monthIndex = new Map(months.map((m, i) => [m, i]));
  const waves = Array.from({ length: k }, () => new Array(months.length).fill(0));
  items.forEach((it, i) => { if (dated[i]) waves[labels[i]][monthIndex.get(ym(it.created))]++; });

  return {
    meta: { title, private: isPrivate, version: VERSION, generated: ymd(Date.now()) },
    numbers: summary(items, dated, isPrivate),
    topics, points, items: itemsOut, edges, spine, months, waves,
    review: review(items, labels, dated, k, edges, topicBridges(Z, d, labels, k)),
    shell: brain.shell(15000, 3 + seed).flat().map(v => round(v, 3)),
  };
}
