"""Geometry for the brain-shaped point cloud.

Coordinates: x = left/right, y = up, z = front (+) / back (-).
The shape is built from a few ellipsoids (hemispheres, temporal lobes,
cerebellum) plus a curved brainstem and spinal cord.
"""

from __future__ import annotations

import numpy as np

# (center, radii)
HEMISPHERES = [
    (np.array([-0.30, 0.15, 0.00]), np.array([0.52, 0.62, 0.95])),
    (np.array([0.30, 0.15, 0.00]), np.array([0.52, 0.62, 0.95])),
]
TEMPORAL = [
    (np.array([-0.50, -0.22, 0.18]), np.array([0.30, 0.30, 0.55])),
    (np.array([0.50, -0.22, 0.18]), np.array([0.30, 0.30, 0.55])),
]
CEREBELLUM = (np.array([0.0, -0.40, -0.62]), np.array([0.52, 0.24, 0.32]))

# Brainstem + spinal cord as a polyline with a radius per vertex.
SPINE_PATH = np.array([
    [0.0, -0.30, -0.22],
    [0.0, -0.70, -0.32],
    [0.0, -1.05, -0.40],
    [0.0, -1.40, -0.45],
    [0.0, -1.85, -0.44],
])
SPINE_RADIUS = np.array([0.13, 0.12, 0.09, 0.07, 0.06])

CEREBRUM = HEMISPHERES + TEMPORAL


def _in_ellipsoid(p: np.ndarray, center: np.ndarray, radii: np.ndarray) -> np.ndarray:
    return (((p - center) / radii) ** 2).sum(axis=-1) <= 1.0


def inside_cerebrum(p: np.ndarray) -> np.ndarray:
    p = np.atleast_2d(p)
    mask = np.zeros(len(p), dtype=bool)
    for c, r in CEREBRUM:
        mask |= _in_ellipsoid(p, c, r)
    return mask


def sample_cerebrum(n: int, rng: np.random.Generator) -> np.ndarray:
    """Uniform random points inside the cerebrum (rejection sampling)."""
    lo, hi = np.array([-0.85, -0.55, -0.98]), np.array([0.85, 0.80, 0.98])
    out = []
    while sum(len(o) for o in out) < n:
        cand = rng.uniform(lo, hi, size=(n * 3, 3))
        out.append(cand[inside_cerebrum(cand)])
    return np.vstack(out)[:n]


def _folds(d: np.ndarray, freq: float) -> np.ndarray:
    """Cheap pseudo-noise used to fake gyri and sulci on the surface."""
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    return (np.sin(freq * x + 2.1 * np.sin(1.7 * freq * z))
            * np.sin(freq * 0.9 * y + 1.3 * np.cos(1.3 * freq * x))
            + 0.5 * np.sin(freq * 1.9 * z + 0.7 * y))


def _ellipsoid_surface(n: int, center, radii, rng, freq=9.0, depth=0.05):
    d = rng.normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    f = _folds(d, freq)
    # Keep mostly the ridges so the folds read as lines, not noise.
    keep = f > -0.15
    d, f = d[keep], f[keep]
    return center + d * radii * (1.0 + depth * f)[:, None]


def shell(n: int = 15000, seed: int = 3) -> np.ndarray:
    """Decorative outline of the brain: surface points with fake folds."""
    rng = np.random.default_rng(seed)
    parts = []
    for c, r in HEMISPHERES:
        pts = _ellipsoid_surface(int(n * 0.36), c, r, rng)
        # Longitudinal fissure: leave a gap between the hemispheres on top.
        pts = pts[~((np.abs(pts[:, 0]) < 0.05) & (pts[:, 1] > -0.1))]
        # Only keep the outer side of each hemisphere.
        pts = pts[np.sign(pts[:, 0]) == np.sign(c[0])]
        parts.append(pts)
    for c, r in TEMPORAL:
        pts = _ellipsoid_surface(int(n * 0.08), c, r, rng, freq=11.0)
        parts.append(pts[~inside_cerebrum_excluding(pts, (c, r))])
    c, r = CEREBELLUM
    d = rng.normal(size=(int(n * 0.12), 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    folia = 1.0 + 0.06 * np.sin(38 * d[:, 1])  # horizontal stripes
    cer = c + d * r * folia[:, None]
    parts.append(cer[~inside_cerebrum(cer)])
    parts.append(spine_points(int(n * 0.06), rng, jitter=1.0))
    return np.vstack(parts)


def inside_cerebrum_excluding(p: np.ndarray, skip) -> np.ndarray:
    mask = np.zeros(len(p), dtype=bool)
    for c, r in CEREBRUM:
        if c is skip[0]:
            continue
        mask |= _in_ellipsoid(p, c, r)
    return mask


def spine_curve(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Point and radius along the spine for t in [0, 1] (0 = bottom, 1 = top)."""
    s = (1.0 - np.asarray(t)) * (len(SPINE_PATH) - 1)
    i = np.clip(np.floor(s).astype(int), 0, len(SPINE_PATH) - 2)
    f = (s - i)[:, None]
    pts = SPINE_PATH[i] * (1 - f) + SPINE_PATH[i + 1] * f
    rad = SPINE_RADIUS[i] * (1 - f[:, 0]) + SPINE_RADIUS[i + 1] * f[:, 0]
    return pts, rad


def spine_points(n: int, rng: np.random.Generator, jitter: float = 0.8,
                 t: np.ndarray | None = None) -> np.ndarray:
    t = rng.random(n) if t is None else np.asarray(t)
    pts, rad = spine_curve(t)
    ang = rng.uniform(0, 2 * np.pi, len(t))
    r = rad * np.sqrt(rng.random(len(t))) * jitter
    pts = pts.copy()
    pts[:, 0] += r * np.cos(ang)
    pts[:, 2] += r * np.sin(ang)
    return pts


def anchors(k: int, seed: int = 11) -> np.ndarray:
    """k well-spread points inside the cerebrum (farthest-point sampling)."""
    rng = np.random.default_rng(seed)
    cand = sample_cerebrum(4000, rng)
    # Stay away from the very edge so clusters have room around them.
    cand = cand[inside_cerebrum(cand * 1.18)]
    chosen = [cand[np.argmax(cand[:, 1])]]
    dist = np.linalg.norm(cand - chosen[0], axis=1)
    for _ in range(1, k):
        nxt = cand[np.argmax(dist)]
        chosen.append(nxt)
        dist = np.minimum(dist, np.linalg.norm(cand - nxt, axis=1))
    return np.array(chosen)


def place_cluster(anchor: np.ndarray, local: np.ndarray, radius: float,
                  rng: np.random.Generator) -> np.ndarray:
    """Put a cluster's points around its anchor and keep them inside the brain."""
    pts = anchor + local * radius + rng.normal(scale=radius * 0.15, size=local.shape)
    for _ in range(12):
        out = ~inside_cerebrum(pts * 1.02)  # small margin, so rounding never pushes a point out
        if not out.any():
            break
        pts[out] = anchor + (pts[out] - anchor) * 0.7
    return pts


# --------------------------------------------------------------------------- #
# galaxy layout: the same points, arranged as a spiral galaxy
# --------------------------------------------------------------------------- #
GALAXY_RADIUS = 1.9


def galaxy(labels: np.ndarray, when: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """One spiral arm per topic. ``when`` is 0..1 (oldest..newest): old ideas sit
    near the core and new ones at the rim, so the galaxy grows outwards in time."""
    n = len(labels)
    rho = 0.42 + (GALAXY_RADIUS - 0.42) * np.asarray(when) ** 0.8
    arm = 2 * np.pi * np.asarray(labels) / max(1, k)
    angle = arm + 1.75 * rho + rng.normal(scale=0.13, size=n)
    rho = rho + rng.normal(scale=0.035 + 0.03 * rho, size=n)
    y = rng.normal(scale=0.05, size=n) * (1.25 - 0.4 * rho / GALAXY_RADIUS)
    return np.column_stack([rho * np.cos(angle), y, rho * np.sin(angle)])


def galaxy_core(when: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """The bright core of the galaxy: every message you wrote, oldest in the centre."""
    n = len(when)
    d = rng.normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
    r = (0.04 + 0.27 * np.asarray(when) ** 0.6) * rng.random(n) ** 0.35
    pts = d * r[:, None]
    pts[:, 1] *= 0.55
    return pts
