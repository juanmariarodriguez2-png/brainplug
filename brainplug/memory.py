"""A memory your AI can read and write: plain Markdown inside your vault.

    <vault>/Brainplug/About me.md     what every assistant should know about you (you write it)
    <vault>/Brainplug/Memory/*.md     one note per thing an assistant was asked to remember

    <vault>/Brainplug/Excluded.md     what you asked to leave out of the brain (one line each)

Every memory is an ordinary note: open it in Obsidian, edit it, move it, delete
it. Nothing is hidden and nothing leaves the folder. An assistant can add
memories and archive them; it never edits "About me" and never deletes a file.

What an assistant asks to keep as a standing preference (pinned, or of kind
"preference") waits for your approval (``pinned: pending``) before it becomes
part of every briefing, so a web page that tricked one assistant cannot plant
instructions for all of them.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

FOLDER = "Brainplug"
MEMORY = "Memory"
PROFILE = "About me.md"
EXCLUDED = "Excluded.md"
TOPIC_NAMES = "Topic names.md"
PENDING = "pending"
KINDS = ("note", "fact", "preference", "decision", "project")
MAX_TEXT = 8000
TEMPLATE_MARK = "brainplug: fill this in"

_TEMPLATES = {
    "en": """---
created: {today}
---
# About me

<!-- {mark}. Assistants read this note at the start of a conversation, so keep it short. -->

- Name:
- What I do:
- What I am working on now:
- How I like answers (language, length, tone):
""",
    "es": """---
created: {today}
---
# Sobre mí

<!-- {mark}. Los asistentes leen esta nota al empezar una conversación, así que mejor breve. -->

- Nombre:
- A qué me dedico:
- En qué estoy trabajando ahora:
- Cómo me gustan las respuestas (idioma, longitud, tono):
""",
}


def brain_dir(vault: str | Path) -> Path:
    return Path(vault).expanduser() / FOLDER


def init(vault: str | Path, lang: str = "en") -> Path:
    """Create the Brainplug folder in a vault (or any folder). Existing notes are left alone."""
    base = brain_dir(vault)
    (base / MEMORY).mkdir(parents=True, exist_ok=True)
    profile = base / PROFILE
    if not profile.exists():
        profile.write_text(_TEMPLATES["es" if lang == "es" else "en"].format(
            today=datetime.now().strftime("%Y-%m-%d"), mark=TEMPLATE_MARK), encoding="utf-8")
    return base


def _split(text: str) -> tuple[dict, str]:
    """Frontmatter (flat ``key: value`` pairs) and body of a note."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key[:1].isspace():
            meta[key.strip().lower()] = value.strip()
    return meta, text[end + 4:].lstrip("\n")


def profile(vault: str | Path) -> str:
    """Your "About me" note as plain text, or "" while it is still the empty template."""
    path = brain_dir(vault) / PROFILE
    if not path.exists():
        return ""
    _, body = _split(path.read_text(encoding="utf-8", errors="ignore"))
    if TEMPLATE_MARK in body:
        filled = [l for l in body.splitlines() if re.match(r"^- [^:]+:\s*\S", l)]
        if not filled:
            return ""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    lines = [l.rstrip() for l in body.splitlines() if l.strip() and not re.match(r"^- [^:]+:\s*$", l)]
    return "\n".join(lines).strip()


def _safe(name: str, limit: int = 70) -> str:
    name = re.sub(r'[\\/:*?"<>|#^\[\]\x00-\x1f]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:limit].rstrip(" .")


def _tag(tag: str) -> str:
    return re.sub(r"[^\w/-]+", "-", tag.strip().lstrip("#"), flags=re.UNICODE).strip("-").lower()


def remember(vault: str | Path, text: str, title: str = "", kind: str = "note", tags: list[str] | tuple = (),
             source: str = "", pin: bool = False, when: datetime | None = None, approved: bool = True,
             replaces: str = "") -> Path:
    """Save one memory as a note in ``Brainplug/Memory`` and return its path.

    ``approved=False`` is for memories an assistant saves: a pinned one, or a
    preference, is marked ``pinned: pending`` until the person approves it.
    ``replaces`` names the memory note this one corrects (see ``supersede``)."""
    text = " ".join(str(text).split()) if "\n" not in str(text).strip() else str(text).strip()
    if not text:
        raise ValueError("There is nothing to remember: the text is empty.")
    text = text[:MAX_TEXT]
    kind = kind if kind in KINDS else "note"
    when = when or datetime.now().astimezone()
    folder = init(vault) / MEMORY
    named = bool(_safe(title))
    title = _safe(title) or _safe(" ".join(text.split()[:9])) or "Memory"
    stem = f"{when:%Y-%m-%d} {title}"
    labels = ["brainplug/memory", f"brainplug/{kind}", *[t for t in map(_tag, tags) if t]]
    head = ["---", f"created: {when.isoformat(timespec='seconds')}", f"kind: {kind}"]
    if _safe(source):
        head.append(f"saved_by: {_safe(source, 40)}")
    if (pin or kind == "preference") and not approved:
        head.append(f"pinned: {PENDING}")  # a standing preference waits for the person's yes
    elif pin:
        head.append("pinned: true")
    if _safe(replaces, 200):
        head.append(f"replaces: {_safe(replaces, 200)}")
    head += [f"tags: [{', '.join(dict.fromkeys(labels))}]", "---", ""]
    head += [f"# {title}", "", text, ""] if named else [text, ""]  # an untitled memory is named after its own words
    n = 1
    while True:  # never overwrite a note, even when two assistants save at the same moment
        path = folder / (f"{stem}.md" if n == 1 else f"{stem} {n}.md")
        try:
            with open(path, "x", encoding="utf-8") as fh:
                fh.write("\n".join(head))
            return path
        except FileExistsError:
            n += 1


def memories(vault: str | Path) -> list[dict]:
    """Every memory that has not been archived, newest first."""
    folder = brain_dir(vault) / MEMORY
    out = []
    for path in sorted(folder.glob("*.md")) if folder.exists() else []:
        meta, body = _split(path.read_text(encoding="utf-8", errors="ignore"))
        if meta.get("archived", "").lower() == "true":
            continue
        body = re.sub(r"^# .*\n+", "", body, count=1).strip()
        pinned = meta.get("pinned", "").lower()
        out.append({"path": path, "name": path.stem, "created": meta.get("created", ""), "kind": meta.get("kind", "note"),
                    "pinned": pinned == "true", "pending": pinned == PENDING, "by": meta.get("saved_by", ""),
                    "text": body})
    out.sort(key=lambda m: (m["created"], m["name"]), reverse=True)
    return out


def _find(vault: str | Path, name: str) -> Path | None:
    folder = brain_dir(vault) / MEMORY
    wanted = _safe(Path(str(name)).stem, 200).lower()
    for path in sorted(folder.glob("*.md")) if folder.exists() and wanted else []:
        if path.stem.lower() == wanted:
            return path
    return None


def _update(path: Path, changes: dict[str, str | None]) -> None:
    """Set (or, with None, remove) flat frontmatter fields and leave the rest of the note as it is."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    end = text.find("\n---", 3) if text.startswith("---") else -1
    head = text[3:end].strip("\n").split("\n") if end >= 0 else []
    rest = text[end + 4:] if end >= 0 else "\n" + text
    out, done = [], set()
    for line in head:
        key = line.partition(":")[0].strip().lower()
        if key in changes and not line[:1].isspace():
            if changes[key] is not None and key not in done:
                out.append(f"{key}: {changes[key]}")
                done.add(key)
            continue
        out.append(line)
    out += [f"{k}: {v}" for k, v in changes.items() if v is not None and k not in done]
    path.write_text("---\n" + "\n".join(line for line in out if line.strip()) + "\n---" + rest, encoding="utf-8")


def forget(vault: str | Path, name: str) -> Path | None:
    """Archive a memory by its note name. The note stays in the vault, marked ``archived: true``,
    and is no longer read; delete the file yourself if you want it gone."""
    path = _find(vault, name)
    if path is not None:
        _update(path, {"archived": "true"})
    return path


def supersede(vault: str | Path, old: str, new: str) -> Path | None:
    """Archive memory ``old`` because memory ``new`` corrects it; each note names the other."""
    path = _find(vault, old)
    if path is not None:
        _update(path, {"archived": "true", "superseded_by": _safe(new, 200)})
    return path


def pending(vault: str | Path) -> list[dict]:
    """Memories assistants saved as standing preferences that still wait for the person's approval."""
    return [m for m in memories(vault) if m["pending"]]


def approve(vault: str | Path, name: str) -> Path | None:
    """The person agrees: the memory becomes part of every briefing."""
    path = _find(vault, name)
    if path is not None:
        _update(path, {"pinned": "true"})
    return path


# ---------------------------------------------------------------- exclusions
_EXCLUDED_HEAD = """---
kind: brainplug-exclusions
---
# Left out of Brainplug

Everything listed here stays out of your brain: the map, search and what assistants read.
Delete a line to bring it back.

"""
_EXCLUDED_LINE = re.compile(r"^\s*[-*]\s+(source:\s*)?`([^`]+)`")


def exclusions(vault: str | Path) -> tuple[set[str], set[str]]:
    """The item ids and the sources listed in ``Brainplug/Excluded.md``."""
    path = brain_dir(vault) / EXCLUDED
    ids: set[str] = set()
    sources: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = _EXCLUDED_LINE.match(line)
            if m:
                (sources if m.group(1) else ids).add(m.group(2).strip())
    return ids, sources


def exclude(vault: str | Path, item_id: str = "", title: str = "", source: str = "", by: str = "",
            reason: str = "") -> Path:
    """Add one line to ``Brainplug/Excluded.md``: an item, or a whole source, to leave out."""
    item_id, source = item_id.replace("`", ""), re.sub(r"[^a-z0-9]", "", source.lower())
    if not item_id and not source:
        raise ValueError("Say which item or which source to leave out.")
    path = init(vault) / EXCLUDED
    if not path.exists():
        path.write_text(_EXCLUDED_HEAD, encoding="utf-8")
    line = f"- source: `{source}`" if source else f"- `{item_id}` · {_safe(title, 80) or 'untitled'}"
    line += f" · {datetime.now():%Y-%m-%d}" + (f" · by {_safe(by, 40)}" if _safe(by) else "")
    line += f": {' '.join(str(reason).split())[:200]}" if str(reason).strip() else ""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return path


# --------------------------------------------------------------- topic names
_NAMES_HEAD = """---
kind: brainplug-topic-names
---
# Topic names

Brainplug names a topic after its strongest words. A name here replaces that, for the topic
whose words match. Edit or delete a line any time.

"""
_NAME_LINE = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*\s+·\s+(.+?)\s*$")
_NAME_OK = re.compile(r"^[\w][\w\s&'’.,()/+-]*$", re.UNICODE)


def clean_topic_name(name: str) -> str:
    """A short label: up to 5 words and 40 characters of letters, digits and simple punctuation."""
    name = " ".join(str(name).split())
    if not name or len(name) > 40 or len(name.split()) > 5 or not _NAME_OK.match(name):
        raise ValueError("A topic name is 1 to 5 words (40 characters at most), letters, digits and simple punctuation.")
    return name


def topic_names(vault: str | Path) -> list[tuple[str, list[str]]]:
    """The names in ``Brainplug/Topic names.md``, each with the words of the topic it names."""
    path = brain_dir(vault) / TOPIC_NAMES
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if path.exists() else []:
        m = _NAME_LINE.match(line)
        if m:
            out.append((m.group(1).strip(), [w.strip().lower() for w in m.group(2).split(",") if w.strip()]))
    return out


def name_topic(vault: str | Path, name: str, terms: list[str]) -> Path:
    """Save a name for the topic with these words, replacing any name it had."""
    name, words = clean_topic_name(name), [w.lower() for w in terms if w]
    if not words:
        raise ValueError("That topic has no words to remember its name by.")
    kept = [(n, t) for n, t in topic_names(vault) if len(set(t) & set(words)) * 3 < max(1, len(t))]
    path = init(vault) / TOPIC_NAMES
    lines = [f"- **{n}** · {', '.join(t)}" for n, t in kept + [(name, words)]]
    path.write_text(_NAMES_HEAD + "\n".join(lines) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------- About me draft
_DRAFT = {
    "en": {"about": "What I write about most", "now": "What I am working on now", "where": "Where I write",
           "when": "When I write", "at": "mostly on {day}s, around {hour}:00",
           "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
           "mark": "a draft from your writing, {d}: check it, fill in the rest and delete what is wrong"},
    "es": {"about": "Sobre lo que más escribo", "now": "En qué estoy trabajando ahora", "where": "Dónde escribo",
           "when": "Cuándo escribo", "at": "sobre todo los {day}, hacia las {hour}:00",
           "days": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos"],
           "mark": "un borrador a partir de lo que escribes, {d}: revísalo, completa el resto y borra lo que no sea cierto"},
}


def draft_profile(vault: str | Path, payload: dict) -> tuple[Path, str, bool]:
    """A draft of "About me" from what the analysis found. Written into the note only while it
    is still the empty template; returns (path, draft, written)."""
    base = init(vault)
    path = base / PROFILE
    text = path.read_text(encoding="utf-8", errors="ignore")
    t = _DRAFT["es" if "# Sobre mí" in text else "en"]
    topics, n, review = payload["topics"], payload["numbers"], payload["review"]
    rising = [topics[x["k"]]["name"] for x in review["rising"][:3]]
    lines = [(t["about"], ", ".join(x["name"] for x in topics[:4])),
             (t["now"], ", ".join(rising) or ", ".join(x["name"] for x in topics[:2])),
             (t["where"], ", ".join(s["name"] for s in n["sources"][:4])),
             (t["when"], t["at"].format(day=t["days"][n["busiest_weekday"]], hour=n["busiest_hour"]))]
    draft = "\n".join(f"- {k}: {v}" for k, v in lines if v)
    if profile(vault):
        return path, draft, False  # yours already: never overwritten
    body = re.sub(rf"(?m)^- {re.escape(t['now'])}:[ \t]*\n?", "", text).rstrip("\n")
    path.write_text(f"{body}\n\n<!-- {t['mark'].format(d=datetime.now().strftime('%Y-%m-%d'))} -->\n{draft}\n",
                    encoding="utf-8")
    return path, draft, True
