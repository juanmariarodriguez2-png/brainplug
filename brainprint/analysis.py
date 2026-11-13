"""Turn items into topics, connections, two 3D layouts and summary numbers."""

from __future__ import annotations

import warnings
from collections import Counter
from datetime import datetime, timedelta, tzinfo

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA, TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize

from . import __version__, brain
from .sources import Item
from .stopwords import STOP_WORDS

PALETTE = [
    "#4cc9f0", "#f72585", "#b8f35a", "#ffb703", "#9d4edd", "#2ec4b6", "#ff6b6b",
    "#ffd6a5", "#80ffdb", "#c77dff", "#f15bb5", "#00bbf9", "#fee440", "#a0c4ff",
    "#ff9f1c", "#06d6a0",
]
KINDS = ["chat", "note", "message"]
SOURCE_NAMES = {
    "chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini", "copilot": "Copilot",
    "perplexity": "Perplexity", "obsidian": "Obsidian", "notion": "Notion", "notes": "Notes",
    "word": "Word", "pdf": "PDF", "gmail": "Gmail", "whatsapp": "WhatsApp", "memory": "Memory",
    "demo": "Demo",
}
TOKEN_PATTERN = r"(?u)\b[^\W\d_][^\W\d_]+\b"


def _stamps(item: Item) -> list[datetime]:
    """When you wrote: one timestamp per message, or the note's own date."""
    return item.parts or [item.created]


# --------------------------------------------------------------------------- #
# topics
# --------------------------------------------------------------------------- #
def documents(items: list[Item]) -> list[str]:
    # Titles and tags are strong hints, so they count twice. Only your own
    # words are used: they say what *you* care about. A WhatsApp "title" is a
    # person's name, which says nothing about the topic, so it is left out.
    return [(f"{i.text[:20000]}" if i.source == "whatsapp" else
             f"{i.title}. {i.title}. {' '.join(i.tags)} {' '.join(i.tags)} {i.text[:20000]}")
            for i in items]


def vectorize(docs: list[str]):
    options = dict(lowercase=True, stop_words=STOP_WORDS, token_pattern=TOKEN_PATTERN,
                   ngram_range=(1, 2), max_features=8000, sublinear_tf=True)
    try:
        vec = TfidfVectorizer(min_df=2 if len(docs) >= 20 else 1, max_df=0.5, **options)
        return vec, vec.fit_transform(docs)
    except ValueError:  # tiny or very repetitive record: keep every term
        vec = TfidfVectorizer(min_df=1, max_df=1.0, **options)
        return vec, vec.fit_transform(docs)


def embed(X, seed: int = 0, model: dict | None = None) -> np.ndarray:
    n_comp = max(2, min(100, X.shape[0] - 1, X.shape[1] - 1))
    svd = TruncatedSVD(n_components=n_comp, random_state=seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # identical documents make the variance ratio 0/0
        Z = svd.fit_transform(X)
    if model is not None:
        model["svd"] = svd
    return normalize(Z)


def choose_k(Z: np.ndarray, seed: int = 0) -> int:
    n = len(Z)
    if n < 12:
        return max(1, min(3, n))
    lo, hi = 4, int(min(14, max(5, n // 12)))
    best_k, best_s = lo, -1.0
    for k in range(lo, hi + 1):
        labels = KMeans(n_clusters=k, n_init=5, random_state=seed).fit_predict(Z)
        s = silhouette_score(Z, labels, metric="cosine", sample_size=min(n, 2000),
                             random_state=seed)
        s += 0.004 * k  # small bonus for more topics so the map isn't too coarse
        if s > best_s:
            best_k, best_s = k, s
    return best_k


def label_topics(X, labels: np.ndarray, vocab: np.ndarray, top: int = 3) -> list[list[str]]:
    overall = np.asarray(X.mean(axis=0)).ravel()
    names = []
    for k in range(labels.max() + 1):
        score = np.asarray(X[labels == k].mean(axis=0)).ravel() - 0.5 * overall
        picked: list[str] = []
        for idx in np.argsort(score)[::-1]:
            term = vocab[idx]
            # skip terms that repeat a word already picked ("pandas" vs "pandas groupby")
            if any(w in p.split() for w in term.split() for p in picked):
                continue
            picked.append(term)
            if len(picked) == top:
                break
        names.append(picked)
    return names


def item_terms(X, vocab: np.ndarray, top: int = 4) -> list[list[str]]:
    out = []
    X = X.tocsr()
    for i in range(X.shape[0]):
        row = X.getrow(i)
        order = np.argsort(row.data)[::-1][: top * 2]
        picked: list[str] = []
        for j in order:
            term = vocab[row.indices[j]]
            if not any(w in p.split() for w in term.split() for p in picked):
                picked.append(term)
            if len(picked) == top:
                break
        out.append(picked)
    return out


# --------------------------------------------------------------------------- #
# connections
# --------------------------------------------------------------------------- #
def connections(Z: np.ndarray, items: list[Item], per_item: int = 3,
                min_sim: float = 0.5, limit: int = 8000) -> list[list]:
    """Edges [i, j, weight, kind]: kind 0 = similar content, 1 = explicit link."""
    n = len(items)
    edges: dict[tuple[int, int], tuple[float, int]] = {}
    if n > 2:
        nn = NearestNeighbors(n_neighbors=min(per_item + 1, n), metric="cosine").fit(Z)
        dist, idx = nn.kneighbors(Z)
        for i in range(n):
            for d, j in zip(dist[i], idx[i]):
                if i != j and 1 - d >= min_sim:
                    key = (min(i, int(j)), max(i, int(j)))
                    edges[key] = (max(edges.get(key, (0.0, 0))[0], float(1 - d)), 0)
    by_title: dict[str, int] = {}
    for i, item in enumerate(items):
        by_title.setdefault(item.title.strip().lower(), i)
    for i, item in enumerate(items):
        for target in item.links:  # [[wikilinks]] and Notion page links
            j = by_title.get(target.strip().lower())
            if j is not None and j != i:
                edges[(min(i, j), max(i, j))] = (1.0, 1)
    out = [[a, b, round(w, 2), kind] for (a, b), (w, kind) in edges.items()]
    out.sort(key=lambda e: (-e[3], -e[2]))
    return out[:limit]


def topic_bridges(Z: np.ndarray, labels: np.ndarray, k: int, ratio: float = 0.6,
                  top: int = 3) -> list[dict]:
    """Pairs of topics joined by items that sit between both: an item is a bridge
    when it is almost as close to another topic's centre as to its own."""
    if k < 2:
        return []
    centres = normalize(np.vstack([Z[labels == t].mean(axis=0) for t in range(k)]))
    sim = Z @ centres.T
    rows = np.arange(len(Z))
    own = sim[rows, labels]
    sim[rows, labels] = -1
    second, s2 = sim.argmax(axis=1), sim.max(axis=1)
    pairs: Counter = Counter()
    examples: dict[tuple[int, int], list] = {}
    for i in np.where((s2 >= ratio * own) & (s2 > 0.2))[0]:
        key = (int(min(labels[i], second[i])), int(max(labels[i], second[i])))
        pairs[key] += 1
        examples.setdefault(key, []).append((float(s2[i]), int(i)))
    return [{"a": a, "b": b, "n": n, "ex": [i for _, i in sorted(examples[(a, b)], reverse=True)[:3]]}
            for (a, b), n in pairs.most_common(top)]


# --------------------------------------------------------------------------- #
# numbers
# --------------------------------------------------------------------------- #
def _longest_streak(days: set) -> int:
    best = cur = 0
    prev = None
    for d in sorted(days):
        cur = cur + 1 if prev is not None and (d - prev).days == 1 else 1
        best = max(best, cur)
        prev = d
    return best


def summary(items: list[Item], dated: np.ndarray, tz: tzinfo, private: bool) -> dict:
    timed = [it for it, ok in zip(items, dated) if ok]
    stamps = [s.astimezone(tz) for it in timed for s in _stamps(it)]
    heat = np.zeros((7, 24), dtype=int)
    for s in stamps:
        heat[s.weekday(), s.hour] += 1
    months = Counter(it.created.astimezone(tz).strftime("%Y-%m") for it in timed)
    busiest = max(months.items(), key=lambda kv: kv[1])
    days = {s.date() for s in stamps}
    longest = max(items, key=lambda it: it.words)
    by_source = Counter(it.source for it in items)
    words_by_source: Counter = Counter()
    for it in items:
        words_by_source[it.source] += it.words
    return {
        "items": len(items),
        "kinds": {k: sum(it.kind == k for it in items) for k in KINDS},
        "writes": len(stamps),
        "words": sum(it.words for it in items),
        "first": min(it.created for it in timed).astimezone(tz).strftime("%Y-%m-%d"),
        "last": max(it.created for it in timed).astimezone(tz).strftime("%Y-%m-%d"),
        "active_days": len(days),
        "streak": _longest_streak(days),
        "busiest_month": {"month": busiest[0], "count": int(busiest[1])},
        "busiest_weekday": int(np.argmax(heat.sum(axis=1))),
        "busiest_hour": int(np.argmax(heat.sum(axis=0))),
        "night_share": round(int(heat[:, 0:6].sum()) / max(1, len(stamps)), 3),
        "longest": {"title": None if private else longest.title, "words": longest.words},
        "sources": [
            {"id": s, "name": SOURCE_NAMES.get(s, s.title()), "count": c,
             "words": int(words_by_source[s])}
            for s, c in by_source.most_common()
        ],
        "undated": int((~dated).sum()),
        "heat": heat.tolist(),
    }


def month_range(first: datetime, last: datetime) -> list[str]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# --------------------------------------------------------------------------- #
# review: what changed, what you dropped, what connects
# --------------------------------------------------------------------------- #
def review(items: list[Item], labels: np.ndarray, dated: np.ndarray, k: int,
           edges: list[list], bridges: list[dict], tz: tzinfo, window_days: int = 60) -> dict:
    idx = [i for i in range(len(items)) if dated[i]]
    last = max(items[i].created for i in idx)
    win = timedelta(days=window_days)
    recent, before = np.zeros(k, dtype=int), np.zeros(k, dtype=int)
    first_seen: list = [None] * k
    last_seen: list = [None] * k
    for i in idx:
        c, t = items[i].created, int(labels[i])
        if c > last - win:
            recent[t] += 1
        elif c > last - 2 * win:
            before[t] += 1
        first_seen[t] = c if first_seen[t] is None else min(first_seen[t], c)
        last_seen[t] = c if last_seen[t] is None else max(last_seen[t], c)
    delta = recent - before
    sizes = np.bincount(labels, minlength=k)

    def row(t):
        return {"k": int(t), "now": int(recent[t]), "before": int(before[t])}

    rising = [row(t) for t in np.argsort(-delta, kind="stable") if delta[t] > 0][:3]
    fading = [row(t) for t in np.argsort(delta, kind="stable") if delta[t] < 0][:3]
    dormant = sorted(
        ({"k": t, "days": (last - last_seen[t]).days,
          "last": last_seen[t].astimezone(tz).strftime("%Y-%m-%d")}
         for t in range(k) if last_seen[t] is not None and (last - last_seen[t]).days >= 90),
        key=lambda d: -sizes[d["k"]],
    )[:3]
    seen = [t for t in range(k) if first_seen[t] is not None]
    newest = None
    if seen:
        t = max(seen, key=lambda t: first_seen[t])
        if (last - first_seen[t]).days <= 150 and first_seen[t] > min(first_seen[s] for s in seen):
            newest = {"k": t, "since": first_seen[t].astimezone(tz).strftime("%Y-%m")}

    # connections between different apps; the most telling ones join different kinds
    # of writing (a note and a chat, say), and each item is shown only once
    cross = [(items[a].kind != items[b].kind, w, a, b) for a, b, w, _kind in edges
             if items[a].source != items[b].source]
    cross.sort(reverse=True)
    picked, shown = [], set()
    for _, _, a, b in cross:
        if a not in shown and b not in shown:
            picked.append([a, b])
            shown.update((a, b))
        if len(picked) == 6:
            break
    target = (last.astimezone(tz).year - 1, last.astimezone(tz).month)
    year_ago = [i for i in idx
                if (items[i].created.astimezone(tz).year, items[i].created.astimezone(tz).month) == target]
    return {
        "window": window_days,
        "rising": rising, "fading": fading, "dormant": dormant, "newest": newest,
        "bridges": bridges,
        "cross": picked,
        "cross_total": len(cross),
        "deep": [int(i) for i in np.argsort([-it.words for it in items], kind="stable")[:5]],
        "year_ago": year_ago[:8],
    }


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def analyse(items: list[Item], tz: tzinfo | None = None, n_topics: int | None = None, private: bool = False,
            rename: dict[int, str] | None = None, title: str = "My Brainprint",
            seed: int = 0, keep: dict | None = None) -> dict:
    """Build everything the viewer needs. Pass a dict as ``keep`` to also get the
    fitted model back (vectorizer, SVD, matrices, labels), e.g. for search."""
    if len(items) < 3:
        raise ValueError("Need at least 3 items (chats, notes, documents or messages) to build a brainprint.")
    rng = np.random.default_rng(seed)
    n = len(items)
    dated = np.array([it.dated for it in items])
    if not dated.any():  # nothing carries a real date: fall back to file dates
        dated[:] = True

    vec, X = vectorize(documents(items))
    vocab = vec.get_feature_names_out()
    model: dict = {}
    Z = embed(X, seed, model)
    k = max(1, min(n_topics or choose_k(Z, seed), len(PALETTE), n))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicates make k-means warn; the result is still fine
        labels = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(Z).labels_
    labels = np.unique(labels, return_inverse=True)[1]  # drop clusters that ended up empty
    k = int(labels.max()) + 1

    # biggest topic first, so topic 1 is always the main one
    order = np.argsort(-np.bincount(labels, minlength=k), kind="stable")
    remap = np.empty(k, dtype=int)
    remap[order] = np.arange(k)
    labels = remap[labels]
    sizes = np.bincount(labels, minlength=k)

    terms = label_topics(X, labels, vocab)
    rename = rename or {}
    topics = [{
        "id": i,
        "name": rename.get(i) or (" · ".join(terms[i][:2]) if terms[i] else f"Topic {i + 1}"),
        "terms": terms[i], "color": PALETTE[i], "count": int(sizes[i]),
        "share": round(float(sizes[i]) / n, 3),
    } for i in range(k)]

    edges = connections(Z, items)
    if keep is not None:
        keep.update(vec=vec, svd=model["svd"], X=X, Z=Z, labels=labels)

    # ---- time, normalised to 0..1 -------------------------------------- #
    stamps = np.array([it.created.timestamp() for it in items])
    t0, t1 = stamps[dated].min(), stamps[dated].max()
    span = max(1.0, t1 - t0)
    when = np.where(dated, np.clip((stamps - t0) / span, 0, 1), 0.0)

    # ---- layout 1: brain ------------------------------------------------ #
    pos = np.zeros((n, 3))
    anchors = brain.anchors(k, seed=11 + seed)
    for i in range(k):
        idx = np.where(labels == i)[0]
        if len(idx) >= 4:
            local = PCA(n_components=3, random_state=seed).fit_transform(Z[idx])
            local /= np.abs(local).max(axis=0) + 1e-9
        else:
            local = rng.normal(scale=0.5, size=(len(idx), 3))
        radius = 0.16 + 0.22 * np.sqrt(len(idx) / sizes.max())
        pos[idx] = brain.place_cluster(anchors[i], local, radius, rng)

    # ---- layout 2: galaxy ----------------------------------------------- #
    gal = brain.galaxy(labels, np.where(dated, when, rng.random(n)), k, rng)

    words = np.array([it.words for it in items], dtype=float)
    size = 0.7 + 1.6 * np.log1p(words) / np.log1p(words.max())
    points = [
        [*(round(float(v), 3) for v in pos[i]), *(round(float(v), 3) for v in gal[i]),
         int(labels[i]), round(float(size[i]), 2), round(float(when[i]), 4),
         KINDS.index(items[i].kind)]
        for i in range(n)
    ]

    own_terms = [None] * n if private else item_terms(X, vocab)
    items_out = []
    for i, it in enumerate(items):
        local = it.created.astimezone(tz)
        items_out.append({
            "t": None if private else it.title,
            "d": local.strftime("%Y-%m-%d"), "h": local.hour,
            "n": it.size, "p": len(_stamps(it)), "w": it.words, "k": int(labels[i]), "s": it.source,
            "x": None if private else " ".join(it.text.split())[:180],
            "tm": own_terms[i], "u": 0 if dated[i] else 1,
        })

    # ---- spine / core: every message you wrote, oldest first ------------ #
    rows = sorted((s.timestamp(), int(labels[i]))
                  for i, it in enumerate(items) if dated[i] for s in _stamps(it))
    if len(rows) > 3000:
        rows = [rows[int(j * len(rows) / 3000)] for j in range(3000)]
    along = np.linspace(0.02, 0.98, len(rows))
    spine_xyz = brain.spine_points(len(rows), rng, jitter=0.85, t=along)
    spine_t = np.clip((np.array([r[0] for r in rows]) - t0) / span, 0, 1)
    core_xyz = brain.galaxy_core(spine_t, rng)
    spine = [
        [*(round(float(v), 3) for v in spine_xyz[j]), *(round(float(v), 3) for v in core_xyz[j]),
         rows[j][1], round(float(spine_t[j]), 4)]
        for j in range(len(rows))
    ]

    # ---- waves: items per month and topic -------------------------------- #
    first = datetime.fromtimestamp(t0, tz)
    last = datetime.fromtimestamp(t1, tz)
    months = month_range(first, last)
    midx = {m: i for i, m in enumerate(months)}
    waves = np.zeros((k, len(months)), dtype=int)
    for i, it in enumerate(items):
        if dated[i]:
            waves[labels[i], midx[it.created.astimezone(tz).strftime("%Y-%m")]] += 1

    return {
        "meta": {"title": title, "private": private, "version": __version__,
                 "generated": datetime.now(tz).strftime("%Y-%m-%d")},
        "numbers": summary(items, dated, tz, private),
        "topics": topics,
        "points": points,
        "items": items_out,
        "edges": edges,
        "spine": spine,
        "months": months,
        "waves": waves.tolist(),
        "review": review(items, labels, dated, k, edges, topic_bridges(Z, labels, k), tz),
        "shell": [round(float(v), 3) for v in brain.shell(seed=3 + seed).ravel()],
    }
