"""A memory your AI can read and write: plain Markdown inside your vault.

    <vault>/Brainprint/About me.md     what every assistant should know about you (you write it)
    <vault>/Brainprint/Memory/*.md     one note per thing an assistant was asked to remember

Every memory is an ordinary note: open it in Obsidian, edit it, move it, delete
it. Nothing is hidden and nothing leaves the folder. An assistant can add
memories and archive them; it never edits "About me" and never deletes a file.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

FOLDER = "Brainprint"
MEMORY = "Memory"
PROFILE = "About me.md"
KINDS = ("note", "fact", "preference", "decision", "project")
MAX_TEXT = 8000
TEMPLATE_MARK = "brainprint: fill this in"

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
    """Create the Brainprint folder in a vault (or any folder). Existing notes are left alone."""
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
             source: str = "", pin: bool = False, when: datetime | None = None) -> Path:
    """Save one memory as a note in ``Brainprint/Memory`` and return its path."""
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
    path, n = folder / f"{stem}.md", 2
    while path.exists():  # never overwrite an existing note
        path = folder / f"{stem} {n}.md"
        n += 1
    labels = ["brainprint/memory", f"brainprint/{kind}", *[t for t in map(_tag, tags) if t]]
    head = ["---", f"created: {when.isoformat(timespec='seconds')}", f"kind: {kind}"]
    if _safe(source):
        head.append(f"saved_by: {_safe(source, 40)}")
    if pin:
        head.append("pinned: true")
    head += [f"tags: [{', '.join(dict.fromkeys(labels))}]", "---", ""]
    head += [f"# {title}", "", text, ""] if named else [text, ""]  # an untitled memory is named after its own words
    path.write_text("\n".join(head), encoding="utf-8")
    return path


def memories(vault: str | Path) -> list[dict]:
    """Every memory that has not been archived, newest first."""
    folder = brain_dir(vault) / MEMORY
    out = []
    for path in sorted(folder.glob("*.md")) if folder.exists() else []:
        meta, body = _split(path.read_text(encoding="utf-8", errors="ignore"))
        if meta.get("archived", "").lower() == "true":
            continue
        body = re.sub(r"^# .*\n+", "", body, count=1).strip()
        out.append({"path": path, "name": path.stem, "created": meta.get("created", ""), "kind": meta.get("kind", "note"),
                    "pinned": meta.get("pinned", "").lower() == "true", "by": meta.get("saved_by", ""), "text": body})
    out.sort(key=lambda m: (m["created"], m["name"]), reverse=True)
    return out


def forget(vault: str | Path, name: str) -> Path | None:
    """Archive a memory by its note name. The note stays in the vault, marked ``archived: true``,
    and is no longer read; delete the file yourself if you want it gone."""
    folder = brain_dir(vault) / MEMORY
    wanted = _safe(Path(str(name)).stem, 200).lower()
    for path in sorted(folder.glob("*.md")) if folder.exists() and wanted else []:
        if path.stem.lower() == wanted:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if text.startswith("---") and "\narchived: true" not in text[:text.find("\n---", 3) + 1]:
                text = text.replace("---\n", "---\narchived: true\n", 1)
                path.write_text(text, encoding="utf-8")
            return path
    return None
