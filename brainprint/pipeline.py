"""One function that goes from your files to the finished HTML.

The command line (``build``), the sync command and the local app all call it,
so they always behave the same.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from . import analysis, sources
from .render import render


def local_tz(name: str | None = None):
    """A named time zone, or None for this computer's own zone. None (rather than
    today's UTC offset) keeps summer and winter time right for every date."""
    return ZoneInfo(name) if name else None


@dataclass
class Options:
    inputs: list[str] = field(default_factory=list)
    out: str = "brainprint.html"
    me: list[str] = field(default_factory=list)  # your email(s) and your WhatsApp name
    pdf: bool = False  # also read PDFs found inside folders
    notion: bool = False  # read Notion through its API (NOTION_TOKEN)
    topics: int | None = None
    private: bool = False
    rename: dict[int, str] = field(default_factory=dict)
    title: str = "My Brainprint"
    lang: str = "en"
    tz: str | None = None
    vault: str | None = None  # write Markdown notes into this Obsidian vault
    json: str | None = None  # also save the raw analysis as JSON
    dataset: str | None = None  # also save a redacted JSON Lines dataset


def describe(items: list[sources.Item]) -> str:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.source] = counts.get(item.source, 0) + 1
    parts = [f"{n} from {analysis.SOURCE_NAMES.get(s, s.title())}"
             for s, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    return f"Loaded {len(items)} items" + (": " + ", ".join(parts) if parts else "") + "."


def load(o: Options, say: Callable[[str], None] = print) -> list[sources.Item]:
    notes: list[str] = []
    items = sources.load(o.inputs, me=o.me, pdf=o.pdf, notes=notes)
    if o.notion:
        from .notion_api import load_notion
        known = {i.id for i in items}
        items += [i for i in load_notion(os.environ.get("NOTION_TOKEN", ""), say=say) if i.id not in known]
        items.sort(key=lambda i: i.created)
    for note in notes:
        say(note)
    return items


def run(o: Options, say: Callable[[str], None] = print) -> tuple[list[sources.Item], dict]:
    """Load, analyse and write everything that was asked for."""
    items = load(o, say)
    say(describe(items))
    payload = analysis.analyse(items, tz=local_tz(o.tz), n_topics=o.topics, private=o.private,
                               rename=o.rename, title=o.title)
    say(f"Found {len(payload['topics'])} topics:")
    for t in payload["topics"]:
        say(f"  {t['id'] + 1:>2}. {t['name']:<34} {t['count']:>5} items  ({', '.join(t['terms'])})")
    out = render(payload, o.out, lang=o.lang)
    say(f"\nSaved {out.resolve()}")
    if o.json:
        Path(o.json).parent.mkdir(parents=True, exist_ok=True)
        Path(o.json).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        say(f"Saved {Path(o.json).resolve()}")
    if o.vault:
        from .export import export_vault
        n = export_vault(items, payload, o.vault)
        say(f"Wrote {n} notes to {Path(o.vault).resolve() / 'Brainprint'}")
    if o.dataset:
        from .export import export_dataset
        n = export_dataset(items, payload, o.dataset)
        say(f"Wrote {n} redacted items to {Path(o.dataset).resolve()}")
        say("Redaction is best effort (emails, links, phone and long numbers). Read the file before sharing it.")
    if o.private:
        say("Private mode: titles and text are not in the HTML. Topic names still are,")
        say("so check them (and use --rename) before sharing.")
    return items, payload
