"""Read everything you have written into one common format.

Supported inputs (files, folders or ZIPs, in any mix):

* ChatGPT and Claude exports  -> ``conversations.json`` (or the export ZIP)
* Gemini via Google Takeout   -> ``MyActivity.json`` (or the Takeout ZIP)
* Live capture                -> the JSON saved by the Brainplug browser extension
* Claude Code and Codex       -> their session logs (``~/.claude/projects``, ``~/.codex/sessions``):
                                 what you typed, never the agent's work, with pasted keys masked
* Obsidian vaults / any folder of Markdown or text notes
* Notion exports ("Markdown & CSV"); see ``notion_api`` for real creation dates
* Gmail via Google Takeout    -> ``.mbox`` (only the mail *you* sent)
* WhatsApp chat exports       -> ``.txt`` or the ZIP (only the messages *you* sent)
* Word and PDF documents      -> ``.docx``, ``.pdf``
* Memories saved by your AI   -> the notes in ``Brainplug/Memory`` (see ``memory``)

Every loader returns ``Item`` objects that hold **only your own words**:
your side of a chat, your notes, the text you typed in an email (quoted
replies and signatures are removed), your side of a WhatsApp chat. Word and
PDF files are the exception: they are read whole, so only add your own.
"""

from __future__ import annotations

import copy
import email
import html
import json
import os
import re
import tempfile
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from email import policy
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

NOTE_SUFFIXES = {".md", ".markdown", ".txt"}
SKIP_DIRS = {"node_modules", "templates", "Templates", "__MACOSX"}
MAX_NOTE_BYTES = 400_000
MAX_ZIP_DEPTH = 4  # the top-level ZIP is depth 1
MAX_ZIP_ENTRIES = 500_000
ZIP_RATIO_MIN_BYTES = 100 * 1024**2
MAX_ZIP_RATIO = 1000
MAX_ZIP_BYTES = 50 * 1024**3  # shared by all descendants of one top-level ZIP
MAX_ZIP_DIRECTORY_BYTES = 128 * 1024**2
ZIP_COPY_CHUNK = 1024**2
NOTION_ID = re.compile(r"\s[0-9a-f]{32}$")


@dataclass
class Item:
    """One thing you wrote: an AI chat, a note or document, or messages to people."""

    id: str
    title: str
    created: datetime
    source: str  # chatgpt, claude, gemini, obsidian, notion, notes, word, pdf, gmail, whatsapp…
    kind: str  # chat (with an AI), note (notes and documents), message (mail, WhatsApp)
    text: str  # only your own words
    parts: list[datetime] = field(default_factory=list)  # one per message you wrote
    size: int = 1  # messages in the thread (both sides); 1 for a note
    links: list[str] = field(default_factory=list)  # titles this item links to
    tags: list[str] = field(default_factory=list)
    dated: bool = True  # False when the source carries no real date
    msgs: list[str] = field(default_factory=list)  # chats: each message you wrote, in step with parts

    @property
    def words(self) -> int:
        return len(self.text.split())


# --------------------------------------------------------------------------- #
# dates
# --------------------------------------------------------------------------- #
_MONTHS = {}
for _i, _names in enumerate([
    "january enero jan ene", "february febrero feb", "march marzo mar", "april abril apr abr",
    "may mayo", "june junio jun", "july julio jul", "august agosto aug ago",
    "september septiembre sep sept", "october octubre oct", "november noviembre nov",
    "december diciembre dec dic",
], start=1):
    for _n in _names.split():
        _MONTHS[_n] = _i


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _from_epoch(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc) if value else None
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def parse_date(value: Any) -> datetime | None:
    """Tolerant date parser: ISO, 03/03/2025, 'March 3, 2025 10:00 AM', '3 de marzo de 2025'."""
    if value in (None, "", []):
        return None
    s = str(value).strip().strip("\"'")
    try:
        return _aware(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        pass
    hour = minute = 0
    t = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp])?", s)
    if t:
        hour, minute = int(t.group(1)) % 24, int(t.group(2))
        if t.group(3):  # 12-hour clock
            hour = hour % 12 + (12 if t.group(3).lower() == "p" else 0)
    y = mo = d = None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    if y is None:
        m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
        if m:
            d, mo, y = map(int, m.groups())
    if y is None:
        m = re.search(r"([^\W\d_]+)\.?\s+(\d{1,2}),?\s+(\d{4})", s)
        if m and m.group(1).lower() in _MONTHS:
            mo, d, y = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
    if y is None:
        m = re.search(r"(\d{1,2})\s+(?:de\s+)?([^\W\d_]+)\.?,?\s+(?:de\s+)?(\d{4})", s)
        if m and m.group(2).lower() in _MONTHS:
            d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
    if y is None:
        return None
    try:
        return datetime(y, mo, d, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# AI chats: ChatGPT and Claude
# --------------------------------------------------------------------------- #
def _chatgpt_text(content: dict) -> str:
    out = []
    for part in content.get("parts") or []:
        if isinstance(part, str):
            out.append(part)
        elif isinstance(part, dict) and isinstance(part.get("text"), str):
            out.append(part["text"])
    if not out and isinstance(content.get("text"), str):
        out.append(content["text"])
    return "\n".join(p for p in out if p.strip()).strip()


def parse_chatgpt(data: list[dict]) -> list[Item]:
    items = []
    for i, conv in enumerate(data):
        mine, total = [], 0
        for node in (conv.get("mapping") or {}).values():
            msg = (node or {}).get("message")
            if not msg:
                continue
            role = (msg.get("author") or {}).get("role")
            if role not in ("user", "assistant"):
                continue
            text = _chatgpt_text(msg.get("content") or {})
            if not text:
                continue
            total += 1
            if role == "user":
                mine.append((_from_epoch(msg.get("create_time")), text))
        created = _from_epoch(conv.get("create_time")) or next((t for t, _ in mine if t), None)
        if created is None or not mine:
            continue
        mine.sort(key=lambda m: m[0] or created)
        items.append(Item(
            id=f"chatgpt:{conv.get('id') or conv.get('conversation_id') or i}",
            title=(conv.get("title") or "Untitled").strip() or "Untitled",
            created=created, source="chatgpt", kind="chat",
            text="\n".join(t for _, t in mine),
            parts=[t or created for t, _ in mine], size=total, msgs=[t for _, t in mine],
        ))
    return items


def parse_claude(data: list[dict]) -> list[Item]:
    items = []
    for i, conv in enumerate(data):
        mine, total = [], 0
        for msg in conv.get("chat_messages") or []:
            sender = msg.get("sender")
            if sender not in ("human", "assistant"):
                continue
            text = (msg.get("text") or "").strip()
            if not text:
                text = "\n".join(
                    c.get("text", "") for c in msg.get("content") or []
                    if isinstance(c, dict) and c.get("type") == "text"
                ).strip()
            if not text:
                continue
            total += 1
            if sender == "human":
                mine.append((parse_date(msg.get("created_at")), text))
        created = parse_date(conv.get("created_at")) or next((t for t, _ in mine if t), None)
        if created is None or not mine:
            continue
        items.append(Item(
            id=f"claude:{conv.get('uuid') or i}",
            title=(conv.get("name") or "").strip() or "Untitled",
            created=created, source="claude", kind="chat",
            text="\n".join(t for _, t in mine),
            parts=[t or created for t, _ in mine], size=total, msgs=[t for _, t in mine],
        ))
    return items


# --------------------------------------------------------------------------- #
# notes: Obsidian, Notion and plain folders
# --------------------------------------------------------------------------- #
def _frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta: dict[str, Any] = {}
    key = None
    for line in text[3:end].splitlines():
        if key and re.match(r"^\s*-\s+\S", line):
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(line.split("-", 1)[1].strip().strip("\"'"))
        elif ":" in line and not line[:1].isspace():
            key, _, val = line.partition(":")
            key, val = key.strip().lower(), val.strip()
            if val.startswith("[") and val.endswith("]"):
                meta[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
            else:
                meta[key] = val.strip("\"'")
    return meta, text[end + 4:]


def clean_markdown(body: str) -> tuple[str, list[str], list[str]]:
    """Return (plain text, linked titles, tags) for a Markdown note."""
    body = re.sub(r"```.*?```", " ", body, flags=re.S)
    links = re.findall(r"(?<!!)\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", body)
    links += re.findall(r"\[([^\]]+)\]\([^)\s]*[0-9a-f]{32}\.md\)", body)  # Notion page links
    body = re.sub(r"!\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)", " ", body)  # embeds and images
    body = re.sub(r"\[\[[^\]|]*\|([^\]]+)\]\]", r"\1", body)
    body = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"https?://\S+|<[^>\n]+>", " ", body)
    tags = re.findall(r"(?<![\w/&])#([^\W\d_][\w/-]*)", body)
    body = re.sub(r"(?m)^\s*(#{1,6}|[-*+>]|\d+[.)])\s+", "", body)
    body = re.sub(r"[*_~`|]{1,3}|(?<![\w/&])#(?=[^\W\d_])", " ", body)
    text = re.sub(r"\s+", " ", body).strip()
    return text, [l.strip() for l in links if l.strip()], tags


def _file_date(path: Path) -> datetime:
    st = path.stat()
    stamps = [st.st_mtime]
    birth = getattr(st, "st_birthtime", None) or (st.st_ctime if os.name == "nt" else None)
    if birth:
        stamps.append(birth)
    return datetime.fromtimestamp(min(stamps), tz=timezone.utc)


def _read(path: Path) -> str:
    with open(path, "rb") as fh:
        return fh.read(MAX_NOTE_BYTES).decode("utf-8", errors="ignore")


_DATE_KEYS = ("created", "date created", "created time", "created at", "created_at", "creado",
              "fecha de creación", "date", "fecha", "last edited time", "last edited", "updated")


def _meta_date(meta: dict) -> datetime | None:
    for key in _DATE_KEYS:
        if key in meta:
            found = parse_date(meta[key])
            if found:
                return found
    return None


# Notes Brainplug wrote itself (--vault) are a copy of things already read, so they are
# skipped; the memory folder and "About me" are read as the source "memory".
_GENERATED = re.compile(r"(?:^|/)Brainplug/(?:Items/|Topics/|Brainplug\.md$|Excluded\.md$)")
_MEMORY = re.compile(r"(?:^|/)Brainplug/(?:Memory/|About me\.md$)")


def parse_note(path: Path, rel: Path, source: str) -> Item | None:
    meta, body = _frontmatter(_read(path))
    if source == "memory":
        if str(meta.get("archived", "")).lower() == "true":
            return None  # a memory you (or an assistant) put away
        if "brainplug: fill this in" in body and not re.search(r"(?m)^- [^:\n]+:[ \t]*\S", body):
            return None  # "About me" is still the empty template
    text, links, tags = clean_markdown(body)
    if len(text.split()) < 3:
        return None
    created = _meta_date(meta)
    if created is None:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", path.stem)  # daily notes
        created = parse_date(m.group(0)) if m else None
    extra = meta.get("tags") or []
    extra = extra if isinstance(extra, list) else re.split(r"[,\s]+", str(extra))
    return Item(
        id=f"{source}:{rel.as_posix()}", title=path.stem, created=created or _file_date(path),
        source=source, kind="note", text=text, links=links,
        tags=sorted({t.lstrip("#") for t in [*tags, *extra] if t}),
    )


def parse_notion_page(path: Path, rel: Path) -> Item | None:
    lines = _read(path).splitlines()
    title = NOTION_ID.sub("", path.stem)
    i = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or title
        i = 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    props: dict[str, str] = {}  # database pages start with "Property: value" lines
    while i < len(lines) and re.match(r"^[^\W\d_][^:\n]{0,40}:\s+\S", lines[i]):
        key, _, val = lines[i].partition(":")
        props[key.strip().lower()] = val.strip()
        i += 1
    text, links, tags = clean_markdown("\n".join(lines[i:]))
    if len(text.split()) < 3:
        return None
    created = _meta_date(props)
    for key in ("tags", "etiquetas", "tag"):
        tags += [t.strip() for t in props.get(key, "").split(",") if t.strip()]
    return Item(
        id=f"notion:{rel.as_posix()}", title=title, created=created or _file_date(path),
        source="notion", kind="note", text=text, links=links, tags=sorted(set(tags)),
        dated=created is not None,
    )


# --------------------------------------------------------------------------- #
# Gmail (Google Takeout .mbox)
# --------------------------------------------------------------------------- #
def _mbox_iter(path: Path, want_body: Callable[[bytes], bool]) -> Iterator[tuple[bytes, bytes, bool]]:
    """Stream an mbox file as (headers, body, kept). The body is only read into
    memory when ``want_body(headers)`` is true, so huge mailboxes stay cheap."""
    headers: list[bytes] = []
    body: list[bytes] = []
    started = in_headers = keep = False
    prev_blank = True
    with open(path, "rb") as fh:
        for line in fh:
            blank = line in (b"\n", b"\r\n")
            if prev_blank and line.startswith(b"From "):
                if started:
                    yield b"".join(headers), b"".join(body), keep
                headers, body, started, in_headers, keep = [], [], True, True, False
            elif started and in_headers:
                if blank:
                    in_headers = False
                    keep = want_body(b"".join(headers))
                else:
                    headers.append(line)
            elif started and keep:
                body.append(line)
            prev_blank = blank
        if started:
            yield b"".join(headers), b"".join(body), keep


def _addresses(msg, name: str) -> list[str]:
    try:
        return [a.lower() for _, a in getaddresses([str(msg.get(name, ""))]) if a]
    except Exception:  # malformed header
        return []


def _headers(raw: bytes):
    try:
        return email.message_from_bytes(raw, policy=policy.default)
    except Exception:
        return None


_REPLY = re.compile(
    r"^(?:On|El|Le)\b[^\n]{0,200}\n?[^\n]{0,120}(?:wrote|escribió|a écrit)\s?:\s*$"
    r"|^-{2,}\s*(?:Original Message|Mensaje original|Forwarded message|Mensaje reenviado)\s*-{2,}\s*$"
    r"|^(?:From|De):\s.+\n(?:Sent|Enviado|Date|Fecha)(?: el)?:\s"
    r"|^(?:Sent from my|Enviado desde mi)\s.+$"
    r"|^-- ?$",
    re.M | re.I,
)


def strip_quoted(text: str) -> str:
    """Keep only what the sender typed: drop quoted replies and signatures."""
    text = text.replace("\r\n", "\n")
    m = _REPLY.search(text)
    if m:
        text = text[: m.start()]
    lines = [l for l in text.split("\n") if not l.lstrip().startswith(">")]
    return re.sub(r"\s+", " ", re.sub(r"https?://\S+", " ", "\n".join(lines))).strip()


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|blockquote)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", markup)
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


def load_gmail(path: Path, me: Iterable[str] | None = None,
               notes: list[str] | None = None) -> list[Item]:
    """Read the mail *you sent* from a Takeout mbox, grouped by thread."""
    mine = {a.lower() for a in (me or [])}
    if not mine:
        # Your own address is the one mail is delivered to (or, in a Sent-only
        # mailbox, the one everything comes from).
        seen: Counter = Counter()
        for raw, _, _ in _mbox_iter(path, lambda h: False):
            msg = _headers(raw)
            if msg is not None:
                seen.update(_addresses(msg, "From") + _addresses(msg, "Delivered-To"))
        if not seen:
            return []
        ranked = seen.most_common(2)
        address, count = ranked[0]
        mine = {address}
        reasons = []
        if count * 2 < sum(seen.values()):
            reasons.append("the address appears in fewer than half of the counted addresses")
        # A runner-up within 20% of the leader is too close to trust silently.
        if len(ranked) > 1 and ranked[1][1] * 5 >= count * 4:
            reasons.append("two addresses have similar counts")
        unsure = f"; unsure: {'; '.join(reasons)}" if reasons else ""
        remark = f"Gmail: kept the mail sent from {address} (detected{unsure}; to change it, give your address in “Who you are” or with --me)."
        if notes is not None and remark not in notes:
            notes.append(remark)

    def sent_by_me(raw: bytes) -> bool:
        msg = _headers(raw)
        return msg is not None and any(a in mine for a in _addresses(msg, "From"))

    threads: dict[str, dict] = {}
    for raw, body, kept in _mbox_iter(path, sent_by_me):
        if not kept:
            continue
        try:
            msg = email.message_from_bytes(raw + b"\n" + body, policy=policy.default)
            part = msg.get_body(preferencelist=("plain", "html"))
            text = part.get_content() if part is not None else ""
            if part is not None and part.get_content_type() == "text/html":
                text = _html_to_text(text)
            when = _aware(parsedate_to_datetime(str(msg["Date"])))
            subject = str(msg.get("Subject", "") or "")
        except Exception:
            continue
        text = strip_quoted(str(text))[:MAX_NOTE_BYTES]
        if not text:
            continue
        subject = re.sub(r"^\s*(?:(?:re|fwd?|rv|fw|tr)\s*:\s*)+", "", subject, flags=re.I).strip()
        key = str(msg.get("X-GM-THRID") or "").strip() or subject.lower()
        thread = threads.setdefault(key, {"subject": subject, "parts": []})
        thread["parts"].append((when, text))

    items = []
    for key, thread in threads.items():
        parts = sorted(thread["parts"], key=lambda p: p[0])
        text = "\n".join(t for _, t in parts)
        if len(text.split()) < 3:
            continue
        items.append(Item(
            id=f"gmail:{key}", title=thread["subject"] or "(no subject)", created=parts[0][0],
            source="gmail", kind="message", text=text, parts=[w for w, _ in parts], size=len(parts),
        ))
    return items


# --------------------------------------------------------------------------- #
# Gemini (Google Takeout > My Activity > Gemini Apps)
# --------------------------------------------------------------------------- #
_GEMINI_PREFIX = re.compile(
    r"^(?:Prompted|Said|Asked|You said|Has preguntado|Preguntaste|Has dicho|Dijiste|Le has dicho|"
    r"Le has preguntado|Solicitaste|Has pedido)[:\s ]+", re.I)
_GEMINI_SKIP = re.compile(r"^(?:Used|Gave feedback|Selected|Created|Usaste|Has usado|Has utilizado|"
                          r"Enviaste comentarios|Has enviado comentarios)\b", re.I)
GEMINI_GAP = 30 * 60  # seconds without a prompt before a new chat starts


def _is_gemini(entry: Any) -> bool:
    if not isinstance(entry, dict) or "time" not in entry or "title" not in entry:
        return False
    tag = " ".join([str(entry.get("header", "")), *map(str, entry.get("products") or [])]).lower()
    return "gemini" in tag or "bard" in tag


def _gemini_items(prompts: list[tuple[datetime, str, str]]) -> list[Item]:
    """Takeout lists single prompts, so chats are rebuilt: by the conversation id
    when the entry has one, otherwise by time (a new chat after a 30 minute gap)."""
    prompts.sort(key=lambda p: p[0])
    groups: dict[tuple, list] = {}
    last, session = None, 0
    for when, text, conv in prompts:
        if conv:
            key = (conv,)
        else:
            if last is None or (when - last).total_seconds() > GEMINI_GAP:
                session += 1
            last, key = when, (session, "by time")
        groups.setdefault(key, []).append((when, text))
    items = []
    for key, turns in groups.items():
        title = " ".join(turns[0][1].split())
        items.append(Item(
            id=f"gemini:{key[0]}" if len(key) == 1 else f"gemini:{turns[0][0]:%Y%m%dT%H%M%S}",
            title=title[:70] + ("…" if len(title) > 70 else ""), created=turns[0][0],
            source="gemini", kind="chat", text="\n".join(t for _, t in turns),
            parts=[w for w, _ in turns], size=2 * len(turns), msgs=[t for _, t in turns],
        ))
    return items


def parse_gemini(data: list[dict]) -> list[Item]:
    prompts = []
    for entry in data:
        if not _is_gemini(entry):
            continue
        when = parse_date(entry.get("time"))
        text = ""
        for detail in entry.get("details") or []:  # older exports: {"name": "Request", "value": …}
            if isinstance(detail, dict) and str(detail.get("name", "")).lower() in ("request", "prompt", "solicitud"):
                text = str(detail.get("value") or "")
        if not text:
            title = html.unescape(str(entry.get("title") or "")).strip()
            if _GEMINI_SKIP.match(title):
                continue
            text = _GEMINI_PREFIX.sub("", title)
        text = text.strip()
        if when is None or not text:
            continue
        conv = re.search(r"/app/(?:c/)?([0-9a-zA-Z_-]{6,})", str(entry.get("titleUrl") or ""))
        prompts.append((when, text, conv.group(1) if conv else ""))
    return _gemini_items(prompts)


def parse_gemini_html(markup: str) -> list[Item]:
    """The default Takeout format is HTML. Best effort: JSON is the reliable one."""
    prompts = []
    for cell in markup.split('<div class="outer-cell')[1:]:
        if not re.search(r"Gemini|Bard", cell[:600]):
            continue
        m = re.search(r'content-cell[^"]*mdl-typography--body-1">(.*?)<br\s*/?>(.*?)<br', cell, re.S)
        if not m:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).replace(" ", " ").strip()
        when = parse_date(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).replace(" ", " "))
        if when is None or _GEMINI_SKIP.match(title):
            continue
        text = _GEMINI_PREFIX.sub("", title).strip()
        if text:
            prompts.append((when, text, ""))
    return _gemini_items(prompts)


# --------------------------------------------------------------------------- #
# coding agents: Claude Code and Codex sessions (what you typed, not the agent's work)
# --------------------------------------------------------------------------- #
# Text the tools put on your side of a session: environment blocks, instructions, command echoes.
_INJECTED = re.compile(r"^\s*(?:<[a-z][\w-]*(?:\s[^<>]*)?>|# AGENTS\.md instructions|Caveat: The messages below|"
                       r"\[Request interrupted)", re.I)
# Keys and tokens people paste into a coding session by mistake.
SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")


def _typed(text: Any) -> str:
    """What you typed to a coding agent, with pasted keys masked; "" for text the tool added."""
    text = str(text or "").strip()
    return "" if not text or _INJECTED.match(text) else SECRET.sub("[secret]", text)


def _text_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or []
                     if isinstance(b, dict) and b.get("type") in ("text", "input_text"))


def parse_session(path: Path) -> Item | None:
    """One Claude Code or Codex session log (JSON Lines), read in one pass."""
    kind, sid, cwd, title, start = "", "", "", "", None
    typed: list[tuple[datetime, str]] = []
    queued: list[tuple[datetime, str]] = []
    events: list[tuple[datetime, str]] = []
    answers = 0
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            when = parse_date(obj.get("timestamp")) or start
            if "sessionId" in obj or obj.get("type") == "summary":  # Claude Code
                kind = kind or ("claudecode" if "sessionId" in obj else "")
                sid, cwd = obj.get("sessionId") or sid, obj.get("cwd") or cwd
                t = obj.get("type")
                if t == "summary":
                    title = title or str(obj.get("summary") or "")
                elif t == "user" and not obj.get("isSidechain") and not obj.get("isMeta"):
                    text = _typed(_text_blocks((obj.get("message") or {}).get("content")))
                    if text and when:
                        typed.append((when, text))
                elif t == "queue-operation" and obj.get("operation") == "enqueue":
                    text = _typed(_text_blocks(obj.get("content")))  # typed while the agent was working
                    if text and when:
                        queued.append((when, text))
                elif t == "attachment" and (obj.get("attachment") or {}).get("type") == "queued_command":
                    sent = obj["attachment"]  # a message delivered while it worked, e.g. with a screenshot
                    if sent.get("humanTurn") is True or (sent.get("origin") or {}).get("kind") == "human":
                        text = _typed(_text_blocks(sent.get("prompt")))
                        if text and when:
                            queued.append((when, text))
                elif t == "assistant" and not obj.get("isSidechain"):
                    answers += bool(_text_blocks((obj.get("message") or {}).get("content")).strip())
                continue
            p = obj["payload"] if isinstance(obj.get("payload"), dict) else obj  # Codex, new and old logs
            if obj.get("type") == "session_meta" or ("instructions" in obj and "id" in obj):
                kind, sid, cwd = "codex", str(p.get("id") or sid), str(p.get("cwd") or cwd)
                start = parse_date(p.get("timestamp")) or start
                continue
            if p.get("type") == "message" and p.get("role") == "user":
                text = _typed(_text_blocks(p.get("content")))
                if text and (when or start):
                    typed.append((when or start, text))
            elif p.get("type") == "message" and p.get("role") == "assistant":
                answers += 1
            elif p.get("type") == "user_message":
                text = _typed(p.get("message"))
                if text and (when or start):
                    events.append((when or start, text))
    if not kind:
        return None
    if kind == "codex" and not typed:
        typed = events  # older logs only record what you typed as events
    left, seen = Counter(_squash(t) for _, t in typed), set()
    for when, text in queued:  # a message typed while the agent worked is logged more than once
        key = _squash(text)
        if key in seen:
            continue
        seen.add(key)
        if left[key]:
            left[key] -= 1
        else:
            typed.append((when, text))
    mine = sorted(typed, key=lambda m: m[0])
    if not mine:
        return None
    project = re.split(r"[\\/]", cwd.rstrip("\\/"))[-1] if cwd else ""
    first = _squash(title or mine[0][1])
    name = first[:70] + ("…" if len(first) > 70 else "")
    return Item(
        id=f"{kind}:{sid or path.stem}", title=f"{project} · {name}" if project else name, created=mine[0][0],
        source=kind, kind="chat", text="\n".join(t for _, t in mine), parts=[w for w, _ in mine],
        msgs=[t for _, t in mine], size=len(mine) + answers,
    )


def _squash(text: str) -> str:
    return " ".join(str(text).split())


def session_folders() -> list[Path]:
    """Where Claude Code and Codex keep their session logs on this computer (those that exist)."""
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser() / "projects"
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser() / "sessions"
    return [p for p in (claude, codex) if p.is_dir()]


# --------------------------------------------------------------------------- #
# live capture (the Brainplug browser extension)
# --------------------------------------------------------------------------- #
def parse_capture(data: dict) -> list[Item]:
    groups: dict[tuple[str, str], list] = {}
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        when = _from_epoch((row.get("ts") or 0) / 1000) if isinstance(row.get("ts"), (int, float)) else parse_date(row.get("ts"))
        site = re.sub(r"[^a-z0-9]", "", str(row.get("site") or "other").lower()) or "other"
        if not text or when is None:
            continue
        conv = str(row.get("conv") or when.strftime("%Y%m%d"))
        groups.setdefault((site, conv), []).append((when, text, str(row.get("title") or "")))
    items = []
    for (site, conv), turns in groups.items():
        turns.sort(key=lambda t: t[0])
        title = next((t for _, _, t in reversed(turns) if t.strip()), "") or " ".join(turns[0][1].split())[:70]
        items.append(Item(
            id=f"{site}:{conv}", title=title.strip(), created=turns[0][0], source=site, kind="chat",
            text="\n".join(t for _, t, _ in turns), parts=[w for w, _, _ in turns], size=2 * len(turns),
            msgs=[t for _, t, _ in turns],
        ))
    return items


def parse_json(data: Any) -> list[Item]:
    """Any JSON Brainplug understands: ChatGPT, Claude, Gemini or the extension's capture file."""
    if isinstance(data, dict) and data.get("format") == "brainplug-capture":
        return parse_capture(data)
    if isinstance(data, list) and data:
        sample = next((c for c in data if isinstance(c, dict)), {})
        if "mapping" in sample:
            return parse_chatgpt(data)
        if "chat_messages" in sample:
            return parse_claude(data)
        if any(_is_gemini(e) for e in data[:50]):
            return parse_gemini(data)
    raise ValueError("Unknown JSON: expected conversations.json from ChatGPT or Claude, "
                     "MyActivity.json from Gemini (Google Takeout) or a Brainplug capture file.")


# --------------------------------------------------------------------------- #
# WhatsApp ("Export chat" > without media)
# --------------------------------------------------------------------------- #
_WA_LINE = re.compile(
    r"^\[?(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4}),? (\d{1,2}):(\d{2})(?::\d{2})?(?: ?([ap])\.? ?m\.?)?\]?"
    r"(?: -)? (.*)$", re.I)
_WA_CLEAN = re.compile("[‎‏‪-‮﻿]")
_WA_NOISE = re.compile(
    r"^<[^>]*>$|\b(?:omitted|omitido|omitida|omitidos)\b|end-to-end|extremo a extremo|"
    r"\((?:file attached|archivo adjunto)\)|^(?:This message was deleted|You deleted this message|"
    r"Eliminaste este mensaje|Se eliminó este mensaje|Missed (?:voice|video) call|Llamada perdida)", re.I)
_WA_NAME = re.compile(r"(?:WhatsApp Chat (?:with|-)|Chat de WhatsApp con|Conversación de WhatsApp con)\s+(.+)$", re.I)
WA_MIN_WORDS = 12


@dataclass
class _WhatsChat:
    name: str  # the other person or the group, when the file name says it
    key: str
    rows: list[tuple[datetime, str, str]]  # when, sender, text


def looks_like_whatsapp(text: str) -> bool:
    lines = [_WA_CLEAN.sub("", l).replace(" ", " ").replace(" ", " ") for l in text[:4000].splitlines()]
    return sum(bool(_WA_LINE.match(l)) for l in lines[:25]) >= 3


def read_whatsapp(text: str, name: str, key: str) -> _WhatsChat:
    raw: list[list] = []
    for line in text.splitlines():
        line = _WA_CLEAN.sub("", line).replace("\u00a0", " ").replace("\u202f", " ")
        m = _WA_LINE.match(line)
        if m:
            raw.append(list(m.groups()))
        elif raw:
            raw[-1][6] += "\n" + line  # a message that continues on the next line
    # 03/04 is ambiguous: look at the whole file to tell day/month order
    day_first = not any(int(r[1]) > 12 for r in raw) or any(int(r[0]) > 12 for r in raw)
    rows = []
    for a, b, y, hh, mm, ap, rest in raw:
        sender, sep, body = rest.partition(": ")
        if not sep:
            continue  # system line ("X added Y", "Messages are encrypted…")
        d, mo = (int(a), int(b)) if day_first else (int(b), int(a))
        year, hour = int(y) + (2000 if len(y) <= 2 else 0), int(hh) % 24
        if ap:
            hour = hour % 12 + (12 if ap.lower() == "p" else 0)
        try:
            when = datetime(year, mo, d, hour, int(mm)).astimezone()  # phone time = local time
        except (ValueError, OSError):
            continue
        body = re.sub(r"<[^>]*(?:edited|editó)[^>]*>", "", body).strip()
        if body and not _WA_NOISE.search(body):
            rows.append((when, sender.strip(), body))
    return _WhatsChat(name=name, key=key, rows=rows)


def whatsapp_me(chats: list[_WhatsChat], names: set[str]) -> set[str]:
    """Who is "you" in these chats? Your own name, lower-cased; empty if unknown."""
    if names:
        return names
    seen: Counter = Counter()
    for chat in chats:
        seen.update({s.lower() for _, s, _ in chat.rows})
    if len(chats) >= 2 and seen:  # you are the one who is in every chat
        name, n = seen.most_common(1)[0]
        if n == len(chats) and sum(1 for c in seen.values() if c == n) == 1:
            return {name}
    found = set()
    for chat in chats:  # a 1:1 chat is named after the other person
        senders = {s.lower() for _, s, _ in chat.rows}
        other = chat.name.lower()
        if len(senders) == 2 and other in senders:
            found |= senders - {other}
    return found if len(found) == 1 else set()


def whatsapp_items(chats: list[_WhatsChat], me: set[str]) -> list[Item]:
    """One item per chat and day, holding only the messages you sent."""
    items = []
    for chat in chats:
        days: dict[str, dict] = {}
        for when, sender, body in chat.rows:
            day = days.setdefault(when.strftime("%Y-%m-%d"), {"mine": [], "total": 0})
            day["total"] += 1
            if sender.lower() in me:
                day["mine"].append((when, re.sub(r"https?://\S+", " ", body)))
        for date, day in days.items():
            text = "\n".join(t for _, t in day["mine"]).strip()
            if len(text.split()) < WA_MIN_WORDS:
                continue
            items.append(Item(
                id=f"whatsapp:{chat.key}:{date}", title=chat.name or "WhatsApp", created=day["mine"][0][0],
                source="whatsapp", kind="message", text=text[:MAX_NOTE_BYTES],
                parts=[w for w, _ in day["mine"]], size=day["total"],
            ))
    return items


# --------------------------------------------------------------------------- #
# documents: Word and PDF
# --------------------------------------------------------------------------- #
def parse_docx(path: Path, rel: Path) -> Item | None:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", "ignore")
            core = zf.read("docProps/core.xml").decode("utf-8", "ignore") if "docProps/core.xml" in zf.namelist() else ""
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    paragraphs = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        para = re.sub(r"<w:(?:tab|br|cr)\b[^>]*/>", " ", para)
        text = html.unescape("".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", para))).strip()
        if text:
            paragraphs.append(text)
    text = re.sub(r"\s+", " ", re.sub(r"https?://\S+", " ", " ".join(paragraphs))).strip()
    if len(text.split()) < 3:
        return None
    title = re.search(r"<dc:title>([^<]+)</dc:title>", core)
    created = re.search(r"<dcterms:created[^>]*>([^<]+)</dcterms:created>", core)
    return Item(
        id=f"word:{rel.as_posix()}", title=(html.unescape(title.group(1)).strip() if title else "") or path.stem,
        created=(parse_date(created.group(1)) if created else None) or _file_date(path),
        source="word", kind="note", text=text[:MAX_NOTE_BYTES],
    )


def parse_pdf(path: Path, rel: Path) -> Item | None:
    try:
        from pypdf import PdfReader
    except ImportError as err:  # pragma: no cover
        raise ValueError("Reading PDF files needs pypdf:  pip install pypdf") from err
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            return None
        pages = [page.extract_text() or "" for page in reader.pages[:300]]
        meta = reader.metadata or {}
        title = str(getattr(meta, "title", None) or "").strip()
        created = getattr(meta, "creation_date", None)
    except Exception:  # damaged or exotic PDF: skip it, keep the rest
        return None
    text = re.sub(r"\s+", " ", re.sub(r"https?://\S+", " ", " ".join(pages))).strip()
    if len(text.split()) < 3:
        return None  # scanned pages have no text layer
    return Item(
        id=f"pdf:{rel.as_posix()}", title=title or path.stem,
        created=_aware(created) if isinstance(created, datetime) else _file_date(path),
        source="pdf", kind="note", text=text[:MAX_NOTE_BYTES],
    )


# --------------------------------------------------------------------------- #
# entry point: files, folders and ZIPs
# --------------------------------------------------------------------------- #
_ZIP_KEEP = NOTE_SUFFIXES | {".mbox", ".zip", ".docx", ".pdf", ".json", ".html"}


def _wanted_json(rel: str) -> bool:
    """Inside folders and ZIPs only JSON files that are clearly exports are read."""
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    return (name == "conversations.json" or "brainplug" in name
            or (("gemini" in low or "bard" in low) and "activ" in name))


class _Loader:
    def __init__(self, me: Iterable[str] | None, pdf: bool, notes: list[str] | None):
        me = [m.strip() for m in (me or []) if m and m.strip()]
        self.emails = [m for m in me if "@" in m]
        self.names = {m.lower() for m in me if "@" not in m}
        self.pdf = pdf
        self.notes = notes if notes is not None else []
        self.chats: list[_WhatsChat] = []

    def json(self, path: Path, strict: bool) -> list[Item]:
        try:
            with open(path, encoding="utf-8") as fh:
                return parse_json(json.load(fh))
        except (ValueError, UnicodeDecodeError):
            if strict:
                raise
            return []

    def zip(self, path: Path) -> list[Item]:
        depth = getattr(self, "_zip_depth", 0)
        if depth == 0:
            self._zip_entries = 0
            self._zip_bytes = 0

        def skip(name: str, why: str) -> None:
            self.notes.append(f"ZIP: skipped {name} ({why}).")

        if depth >= MAX_ZIP_DEPTH:
            skip(path.name, "nesting depth limit")
            return []
        self._zip_depth = depth + 1
        try:
            # ZipFile eagerly allocates the central directory. Inspect it with bounded
            # reads first; count actual records rather than trusting the EOCD count.
            with path.open("rb") as fh:
                end = zipfile._EndRecData(fh)
                if not end:
                    raise zipfile.BadZipFile("Not a ZIP file")
                size = end[zipfile._ECD_SIZE]
                if size > MAX_ZIP_DIRECTORY_BYTES:
                    skip(path.name, "central directory byte limit")
                    return []
                start = end[zipfile._ECD_LOCATION] - size
                fh.seek(max(0, start))
                if fh.read(4) != b"PK\x01\x02" and end[0] == b"PK\x06\x06":
                    start -= 76  # older Python versions leave the ZIP64 trailer here
                fh.seek(max(0, start))
                examined = 0
                while examined < size:
                    if self._zip_entries >= MAX_ZIP_ENTRIES:
                        skip(path.name, "entry count limit")
                        return []
                    head = fh.read(46)
                    if len(head) != 46 or head[:4] != b"PK\x01\x02":
                        raise zipfile.BadZipFile("Damaged central directory")
                    self._zip_entries += 1
                    extra = sum(int.from_bytes(head[i:i + 2], "little") for i in (28, 30, 32))
                    fh.seek(extra, 1)
                    examined += 46 + extra
            with zipfile.ZipFile(path) as zf, tempfile.TemporaryDirectory(prefix="brainplug_") as tmp:
                root = Path(tmp)
                for info in zf.infolist():
                    suffix = Path(info.filename).suffix.lower()
                    if info.is_dir() or suffix not in _ZIP_KEEP:
                        continue
                    low = info.filename.lower()
                    if (suffix == ".json" and not _wanted_json(low)) or \
                            (suffix == ".html" and not ("gemini" in low and "activ" in low)):
                        continue
                    why = None
                    if suffix == ".zip" and self._zip_depth >= MAX_ZIP_DEPTH:
                        why = "nesting depth limit"
                    elif info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        # Older Python ZipExtFile versions inflate BZIP2/LZMA in
                        # unbounded calls, even when read() requests a small chunk.
                        why = "unsupported compression for bounded extraction"
                    elif info.file_size > ZIP_RATIO_MIN_BYTES and info.file_size > MAX_ZIP_RATIO * info.compress_size:
                        why = "compression ratio limit"
                    elif info.file_size > MAX_ZIP_BYTES - self._zip_bytes:
                        why = "extracted byte budget"
                    if why:
                        skip(info.filename, why)
                        continue
                    # Match extract()'s path sanitization without its unbounded copy.
                    name = info.filename.replace("/", os.path.sep)
                    if os.path.altsep:
                        name = name.replace(os.path.altsep, os.path.sep)
                    parts = [p for p in os.path.splitdrive(name)[1].split(os.path.sep) if p not in ("", ".", "..")]
                    if os.path.sep == "\\":
                        parts = [zipfile.ZipFile._sanitize_windows_name(p, "\\") for p in parts]
                    target = root.joinpath(*parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    try:
                        # ZipExtFile otherwise silently truncates at file_size. Allow
                        # one extra byte so even a forged CRC for a prefix is rejected.
                        probe = copy.copy(info)
                        probe.file_size = min(info.file_size, MAX_ZIP_BYTES - self._zip_bytes) + 1
                        with zf.open(probe) as src, target.open("wb") as dst:
                            while chunk := src.read(ZIP_COPY_CHUNK):
                                if written + len(chunk) > info.file_size:
                                    raise ValueError("output exceeds declared size")
                                if len(chunk) > MAX_ZIP_BYTES - self._zip_bytes:
                                    raise ValueError("extracted byte budget")
                                self._zip_bytes += len(chunk)
                                written += len(chunk)
                                dst.write(chunk)
                        if written != info.file_size:
                            raise ValueError("output differs from declared size")
                    except (ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile, zlib.error) as exc:
                        target.unlink(missing_ok=True)
                        skip(info.filename, f"invalid ZIP data or declared size: {exc}")
                        continue
                    try:
                        stamp = datetime(*info.date_time).timestamp()
                        os.utime(target, (stamp, stamp))
                    except (ValueError, OSError):
                        pass
                is_vault = any("/.obsidian/" in "/" + i.filename for i in zf.infolist())
                return self.folder(root, is_vault, hint=path.stem)
        finally:
            self._zip_depth = depth

    def folder(self, root: Path, is_vault: bool = False, hint: str = "") -> list[Item]:
        is_vault = is_vault or (root / ".obsidian").exists() or any(root.glob("*/.obsidian"))
        items: list[Item] = []
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if any(p.startswith(".") or p in SKIP_DIRS for p in rel.parts) or not path.is_file():
                continue
            items += self.file(path, rel, "obsidian" if is_vault else "notes", inside=True, hint=hint)
        return items

    def file(self, path: Path, rel: Path, note_source: str = "notes", inside: bool = False,
             hint: str = "") -> list[Item]:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return self.json(path, strict=not inside) if (not inside or _wanted_json(rel.as_posix())) else []
        if suffix == ".html":
            low = rel.as_posix().lower()
            return parse_gemini_html(_read_all(path)) if (not inside or ("gemini" in low and "activ" in low)) else []
        if suffix == ".mbox":
            return load_gmail(path, self.emails, self.notes)
        if suffix == ".jsonl":
            session = parse_session(path)
            return [session] if session else []
        if suffix == ".zip":
            return self.zip(path)
        if suffix == ".docx":
            doc = None if path.name.startswith("~$") else parse_docx(path, rel)
            return [doc] if doc else []
        if suffix == ".pdf":
            if inside and not self.pdf:
                return []  # PDFs in a folder are usually other people's writing
            doc = parse_pdf(path, rel)
            return [doc] if doc else []
        if suffix in NOTE_SUFFIXES:
            if suffix == ".txt":
                text = _read_all(path)
                if looks_like_whatsapp(text):
                    m = _WA_NAME.search(path.stem) or _WA_NAME.search(hint)
                    name = (m.group(1).strip() if m else "") or (hint if path.stem == "_chat" else path.stem)
                    self.chats.append(read_whatsapp(text, name, key=name or rel.as_posix()))
                    return []
            where = rel.as_posix()
            if _GENERATED.search(where):
                return []
            if suffix != ".txt" and NOTION_ID.search(path.stem):
                note = parse_notion_page(path, rel)
            else:
                note = parse_note(path, rel, "memory" if _MEMORY.search(where) else note_source)
            return [note] if note else []
        return []

    def whatsapp(self) -> list[Item]:
        if not self.chats:
            return []
        me = whatsapp_me(self.chats, self.names)
        if not me:
            senders = sorted({s for c in self.chats for _, s, _ in c.rows})[:6]
            self.notes.append(
                "WhatsApp: unsure: could not tell which sender is you, so those chats were skipped. "
                f'Give your name as it appears in the chat in “Who you are” or with --me (seen: {", ".join(senders)}).')
            return []
        if not self.names:
            sender = next((s for c in self.chats for _, s, _ in c.rows if s.lower() in me), sorted(me)[0])
            evidence = f"{len(self.chats)} chats" if len(self.chats) != 1 else "the file name"
            self.notes.append(
                f"WhatsApp: kept the messages written by {sender} (detected from {evidence}; "
                'to change it, give your name in “Who you are” or with --me).')
        return whatsapp_items(self.chats, me)


def _read_all(path: Path) -> str:
    with open(path, "rb") as fh:
        return fh.read(60_000_000).decode("utf-8", errors="ignore")


def load(paths: Iterable[str | Path], me: Iterable[str] | None = None, pdf: bool = False,
         notes: list[str] | None = None) -> list[Item]:
    """Load any mix of exports, folders and ZIPs. Oldest item first.

    ``me``    your email addresses (Gmail) and your name as shown in WhatsApp.
    ``pdf``   also read the PDFs found inside folders and ZIPs.
    ``notes`` a list that receives human-readable remarks (skipped inputs…).
    """
    paths = list(paths)
    loader = _Loader(me, pdf, notes)
    found: list[Item] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Not found: {path}")
        found += loader.folder(path) if path.is_dir() else loader.file(path, Path(path.name))
    found += loader.whatsapp()
    items: dict[str, Item] = {}
    for item in found:
        old = items.get(item.id)
        if old is None:
            items[item.id] = item
        elif old.text == item.text:
            continue  # the same thing reached twice, e.g. a folder given twice
        elif old.msgs and item.msgs:
            items[item.id] = merge_chats(old, item)  # an export and a later live capture of one chat
        elif item.kind == "note":
            n = 2  # a different note at the same place in another folder: keep both
            while f"{item.id}#{n}" in items:
                n += 1
            item.id = f"{item.id}#{n}"
            items[item.id] = item
        elif item.words > old.words:
            items[item.id] = item  # an older and a newer export of the same thread
    left_out, left_out_sources = _exclusions(paths)
    return sorted((i for i in items.values() if i.id not in left_out and i.source not in left_out_sources),
                  key=lambda i: i.created)


def _exclusions(paths: list) -> tuple[set[str], set[str]]:
    """What the person asked to leave out (Brainplug/Excluded.md in a vault you pass)."""
    from .memory import exclusions  # here: memory does not depend on this module
    ids: set[str] = set()
    names: set[str] = set()
    for raw in paths:
        root = Path(raw).expanduser()
        if root.is_dir():
            for note in [*root.glob("Brainplug/Excluded.md"), *root.glob("*/Brainplug/Excluded.md")]:
                vault = note.parent.parent
                more_ids, more_names = exclusions(vault)
                ids |= more_ids
                names |= more_names
                if vault != root:  # the vault is a folder inside what you passed: its notes' ids say so
                    ids |= {f"{s}:{vault.name}/{rest}" for s, _, rest in (i.partition(":") for i in more_ids)}
    return ids, names


def _same(text: str) -> str:
    return " ".join(text.split())


def merge_chats(a: Item, b: Item) -> Item:
    """One conversation found in two places (an export and the extension's capture made
    after it): keep every message once. A message both have is counted once per copy."""
    base, other = (a, b) if len(a.msgs) >= len(b.msgs) else (b, a)
    unmatched = Counter(_same(m) for m in base.msgs)
    extra = []
    for when, text in zip(other.parts, other.msgs):
        key = _same(text)
        if unmatched[key]:
            unmatched[key] -= 1
        else:
            extra.append((when, text))
    if not extra:
        return base
    rows = sorted([*zip(base.parts, base.msgs), *extra], key=lambda r: r[0])
    return replace(base, title=base.title if base.title not in ("", "Untitled") else other.title,
                   created=min(base.created, other.created), text="\n".join(t for _, t in rows),
                   parts=[w for w, _ in rows], msgs=[t for _, t in rows], size=base.size + 2 * len(extra))
