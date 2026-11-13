"""Write your record back as Markdown notes that Obsidian can open.

Creates a ``Brainprint/`` folder with:

* ``Brainprint.md``        an index of your topics
* ``Topics/<topic>.md``    one map-of-content per topic, grouped by month
* ``Items/<source>/…md``   one note per chat or email, with what you wrote
                           and ``[[links]]`` to related items

Notes that already live in your vault are linked by name, never copied.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .analysis import SOURCE_NAMES
from .sources import Item

MAX_TEXT = 6000


def safe_name(name: str, limit: int = 90) -> str:
    name = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:limit].rstrip(" .") or "Untitled"


def _slug(name: str) -> str:
    return re.sub(r"[^\w]+", "-", name.lower(), flags=re.UNICODE).strip("-") or "topic"


def export_vault(items: list[Item], payload: dict, out_dir: str | Path) -> int:
    base = Path(out_dir) / "Brainprint"
    topics, meta = payload["topics"], payload["items"]
    used: set[str] = set()
    names: dict[int, str] = {}
    own: set[int] = set()  # items we write a note for
    for i, item in enumerate(items):
        if item.source in ("obsidian", "notes"):
            names[i] = safe_name(item.title)  # already a note in the vault
            continue
        name = safe_name(f"{item.title} ({meta[i]['d']})")
        n = 2
        while name.lower() in used:
            name = safe_name(f"{item.title} ({meta[i]['d']}) {n}")
            n += 1
        used.add(name.lower())
        names[i] = name
        own.add(i)

    related: dict[int, list[int]] = defaultdict(list)
    for a, b, _w, _kind in payload["edges"]:
        related[a].append(b)
        related[b].append(a)

    written = 0
    for i in sorted(own):
        item, topic = items[i], topics[meta[i]["k"]]
        folder = base / "Items" / SOURCE_NAMES.get(item.source, item.source.title())
        folder.mkdir(parents=True, exist_ok=True)
        text = item.text[:MAX_TEXT] + (" […]" if len(item.text) > MAX_TEXT else "")
        lines = [
            "---", f"date: {meta[i]['d']}", f"source: {item.source}", f"type: {item.kind}",
            f'topic: "{topic["name"]}"', f"tags: [brainprint, brainprint/{_slug(topic['name'])}]",
            "---", "", f"# {item.title}", "", f"Topic: [[{safe_name(topic['name'])}]]", "",
            "## What I wrote", "", text, "",
        ]
        if related[i]:
            lines += ["## Related", ""] + [f"- [[{names[j]}]]" for j in related[i][:8]] + [""]
        (folder / f"{names[i]}.md").write_text("\n".join(lines), encoding="utf-8")
        written += 1

    (base / "Topics").mkdir(parents=True, exist_ok=True)
    for topic in topics:
        by_month: dict[str, list[int]] = defaultdict(list)
        for i, m in enumerate(meta):
            if m["k"] == topic["id"]:
                by_month["No date" if m["u"] else m["d"][:7]].append(i)
        lines = ["---", "type: topic", f"items: {topic['count']}", "tags: [brainprint]", "---", "",
                 f"# {topic['name']}", "", f"Key terms: {', '.join(topic['terms'])}", ""]
        for month in sorted(by_month, reverse=True):
            lines += [f"## {month}", ""]
            lines += [f"- [[{names[i]}]] · {SOURCE_NAMES.get(items[i].source, items[i].source)}"
                      f" · {meta[i]['d']}" for i in reversed(by_month[month])]
            lines.append("")
        (base / "Topics" / f"{safe_name(topic['name'])}.md").write_text("\n".join(lines), encoding="utf-8")
        written += 1

    numbers = payload["numbers"]
    index = ["# Brainprint", "", f"{numbers['items']} items · {numbers['first']} → {numbers['last']}", "",
             "## Topics", ""]
    index += [f"- [[{safe_name(t['name'])}]] · {t['count']} items ({round(t['share'] * 100)}%)" for t in topics]
    (base / "Brainprint.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return written + 1


# --------------------------------------------------------------------------- #
# research dataset
# --------------------------------------------------------------------------- #
_REDACT = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"(?:https?://|www\.)\S+"), "[url]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"), "[iban]"),
    # 9 digits or more, with the usual separators (a date such as 2025-03-04 has only 8)
    (re.compile(r"(?<!\w)\+?\d[\d ().-]{7,}\d(?!\w)"),
     lambda m: "[phone]" if sum(c.isdigit() for c in m.group()) >= 9 else m.group()),
    (re.compile(r"\b\d{5,}\b"), "[number]"),
    (re.compile(r"(?<!\w)@\w{2,}"), "[handle]"),
]


def redact(text: str) -> str:
    """Mask the obvious identifiers: emails, links, phone and account numbers,
    long numbers and @handles. Names and anything else you wrote stay as they are."""
    for pattern, label in _REDACT:
        text = pattern.sub(label, text)
    return text


def export_dataset(items: list[Item], payload: dict, out: str | Path) -> int:
    """Write your own words as a JSON Lines file you could hand to a researcher.

    One line per item: month, source, kind, topic, word count and the redacted
    text. Titles, exact dates and ids are left out. This is **best-effort
    redaction, not anonymisation**: read the file before you share it.
    """
    import json

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    topics, meta = payload["topics"], payload["items"]
    with open(out, "w", encoding="utf-8") as fh:
        for i, item in enumerate(items):
            fh.write(json.dumps({
                "n": i + 1, "month": meta[i]["d"][:7] if not meta[i]["u"] else None,
                "source": item.source, "kind": item.kind, "topic": topics[meta[i]["k"]]["name"],
                "words": item.words, "text": redact(item.text[:MAX_TEXT * 4]),
            }, ensure_ascii=False) + "\n")
    return len(items)
