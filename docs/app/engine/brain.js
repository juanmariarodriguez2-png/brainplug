// Geometry for the brain-shaped point cloud and for the spiral galaxy.
// A port of brainprint/brain.py: x = left/right, y = up, z = front (+) / back (-).

const HEMISPHERES = [[[-0.30, 0.15, 0.00], [0.52, 0.62, 0.95]], [[0.30, 0.15, 0.00], [0.52, 0.62, 0.95]]];
const TEMPORAL = [[[-0.50, -0.22, 0.18], [0.30, 0.30, 0.55]], [[0.50, -0.22, 0.18], [0.30, 0.30, 0.55]]];
const CEREBELLUM = [[0.0, -0.40, -0.62], [0.52, 0.24, 0.32]];
const SPINE_PATH = [[0, -0.30, -0.22], [0, -0.70, -0.32], [0, -1.05, -0.40], [0, -1.40, -0.45], [0, -1.85, -0.44]];
const SPINE_RADIUS = [0.13, 0.12, 0.09, 0.07, 0.06];
const CEREBRUM = [...HEMISPHERES, ...TEMPORAL];
export const GALAXY_RADIUS = 1.9;

/** Small seeded random generator with the few distributions the layout needs. */
export function makeRng(seed) {
  let a = seed >>> 0;
  const random = () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const normal = (scale = 1) => scale * Math.sqrt(-2 * Math.log(random() + 1e-12)) * Math.cos(2 * Math.PI * random());
  return { random, normal, uniform: (lo, hi) => lo + (hi - lo) * random(), int: n => Math.floor(random() * n) };
}

const inEllipsoid = (x, y, z, [c, r]) => ((x - c[0]) / r[0]) ** 2 + ((y - c[1]) / r[1]) ** 2 + ((z - c[2]) / r[2]) ** 2 <= 1;
export const insideCerebrum = (x, y, z, skip = -1) => CEREBRUM.some((e, i) => i !== skip && inEllipsoid(x, y, z, e));

function sampleCerebrum(n, rng) {
  const out = [];
  while (out.length < n) {
    const p = [rng.uniform(-0.85, 0.85), rng.uniform(-0.55, 0.80), rng.uniform(-0.98, 0.98)];
    if (insideCerebrum(...p)) out.push(p);
  }
  return out;
}

/** k well-spread points inside the cerebrum (farthest-point sampling). */
export function anchors(k, seed = 11) {
  const rng = makeRng(seed);
  const cand = sampleCerebrum(4000, rng).filter(p => insideCerebrum(p[0] * 1.18, p[1] * 1.18, p[2] * 1.18));
  const dist2 = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
  const chosen = [cand.reduce((best, p) => (p[1] > best[1] ? p : best))];
  const d = cand.map(p => dist2(p, chosen[0]));
  for (let i = 1; i < k; i++) {
    let far = 0;
    for (let j = 1; j < cand.length; j++) if (d[j] > d[far]) far = j;
    chosen.push(cand[far]);
    for (let j = 0; j < cand.length; j++) d[j] = Math.min(d[j], dist2(cand[j], cand[far]));
  }
  return chosen;
}

/** Put a cluster's points around its anchor and keep them inside the brain. */
export function placeCluster(anchor, local, radius, rng) {
  const pts = local.map(l => [0, 1, 2].map(a => anchor[a] + l[a] * radius + rng.normal(radius * 0.15)));
  for (let round = 0; round < 12; round++) {
    let moved = false;
    for (const p of pts) {
      if (!insideCerebrum(p[0] * 1.02, p[1] * 1.02, p[2] * 1.02)) {
        for (let a = 0; a < 3; a++) p[a] = anchor[a] + (p[a] - anchor[a]) * 0.7;
        moved = true;
      }
    }
    if (!moved) break;
  }
  return pts;
}

function spineCurve(t) {
  const s = (1 - t) * (SPINE_PATH.length - 1);
  const i = Math.max(0, Math.min(SPINE_PATH.length - 2, Math.floor(s)));
  const f = s - i;
  return [[0, 1, 2].map(a => SPINE_PATH[i][a] * (1 - f) + SPINE_PATH[i + 1][a] * f),
    SPINE_RADIUS[i] * (1 - f) + SPINE_RADIUS[i + 1] * f];
}

export function spinePoints(n, rng, jitter = 0.8, t = null) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const [p, rad] = spineCurve(t ? t[i] : rng.random());
    const ang = rng.uniform(0, 2 * Math.PI), r = rad * Math.sqrt(rng.random()) * jitter;
    out.push([p[0] + r * Math.cos(ang), p[1], p[2] + r * Math.sin(ang)]);
  }
  return out;
}

const unit = rng => {
  const d = [rng.normal(), rng.normal(), rng.normal()], len = Math.hypot(...d) + 1e-9;
  return d.map(v => v / len);
};
const folds = ([x, y, z], freq) => Math.sin(freq * x + 2.1 * Math.sin(1.7 * freq * z))
  * Math.sin(freq * 0.9 * y + 1.3 * Math.cos(1.3 * freq * x)) + 0.5 * Math.sin(freq * 1.9 * z + 0.7 * y);

function ellipsoidSurface(n, [c, r], rng, freq = 9, depth = 0.05) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const d = unit(rng), f = folds(d, freq);
    if (f > -0.15) out.push([0, 1, 2].map(a => c[a] + d[a] * r[a] * (1 + depth * f)));  // keep the ridges
  }
  return out;
}

/** Decorative outline of the brain: surface points with fake folds. */
export function shell(n = 15000, seed = 3) {
  const rng = makeRng(seed);
  const parts = [];
  for (const h of HEMISPHERES) {
    parts.push(...ellipsoidSurface(Math.floor(n * 0.36), h, rng)
      .filter(p => !(Math.abs(p[0]) < 0.05 && p[1] > -0.1) && Math.sign(p[0]) === Math.sign(h[0][0])));
  }
  TEMPORAL.forEach((t, i) => {
    parts.push(...ellipsoidSurface(Math.floor(n * 0.08), t, rng, 11).filter(p => !insideCerebrum(p[0], p[1], p[2], 2 + i)));
  });
  const [c, r] = CEREBELLUM;
  for (let i = 0, m = Math.floor(n * 0.12); i < m; i++) {
    const d = unit(rng), folia = 1 + 0.06 * Math.sin(38 * d[1]);
    const p = [0, 1, 2].map(a => c[a] + d[a] * r[a] * folia);
    if (!insideCerebrum(...p)) parts.push(p);
  }
  parts.push(...spinePoints(Math.floor(n * 0.06), rng, 1.0));
  return parts;
}

/** One spiral arm per topic; `when` is 0..1, so the galaxy grows outwards in time. */
export function galaxy(labels, when, k, rng) {
  return Array.from(labels, (label, i) => {
    let rho = 0.42 + (GALAXY_RADIUS - 0.42) * when[i] ** 0.8;
    const angle = 2 * Math.PI * label / Math.max(1, k) + 1.75 * rho + rng.normal(0.13);
    rho += rng.normal(0.035 + 0.03 * rho);
    const y = rng.normal(0.05) * (1.25 - 0.4 * rho / GALAXY_RADIUS);
    return [rho * Math.cos(angle), y, rho * Math.sin(angle)];
  });
}

/** The bright core of the galaxy: every message you wrote, oldest in the centre. */
export function galaxyCore(when, rng) {
  return Array.from(when, w => {
    const d = unit(rng), r = (0.04 + 0.27 * w ** 0.6) * rng.random() ** 0.35;
    return [d[0] * r, d[1] * r * 0.55, d[2] * r];
  });
}
