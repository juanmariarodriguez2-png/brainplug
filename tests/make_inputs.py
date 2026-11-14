"""Write the synthetic demo data in each app's real export format.

Used by the tests (Python and JavaScript engines must read the same files the
same way) and handy for trying things out::

    python tests/make_inputs.py some/folder 240
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from brainplug import demo  # noqa: E402
from helpers import tiny_docx, tiny_pdf  # noqa: E402

LOCAL = ZoneInfo("Europe/Madrid")


def write_inputs(out: Path, n: int = 240, pdf: bool = True) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    by: dict[str, list] = {}
    for it in demo.generate(n=n):
        by.setdefault(it.source, []).append(it)

    # ChatGPT: a mapping tree per conversation
    convs = []
    for i, it in enumerate(by.get("chatgpt", [])):
        mapping = {"root": {"message": None}}
        for j, (line, when) in enumerate(zip(it.text.split("\n"), it.parts)):
            mapping[f"u{j}"] = {"message": {"author": {"role": "user"}, "create_time": when.timestamp(),
                                            "content": {"content_type": "text", "parts": [line]}}}
            mapping[f"a{j}"] = {"message": {"author": {"role": "assistant"}, "create_time": when.timestamp() + 5,
                                            "content": {"content_type": "text", "parts": ["Sure ASSISTANTWORD."]}}}
        convs.append({"id": f"g{i}", "title": it.title, "create_time": it.created.timestamp(), "mapping": mapping})
    with zipfile.ZipFile(out / "chatgpt-export.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("conversations.json", json.dumps(convs))
        zf.writestr("chat.html", "<html></html>")
        zf.writestr("user.json", "{}")

    # Claude: a flat list of messages
    convs = [{"uuid": f"c{i}", "name": it.title, "created_at": it.created.isoformat(), "chat_messages": sum(([
        {"sender": "human", "text": line, "created_at": when.isoformat()},
        {"sender": "assistant", "text": "Of course ASSISTANTWORD.", "created_at": when.isoformat()},
    ] for line, when in zip(it.text.split("\n"), it.parts)), [])} for i, it in enumerate(by.get("claude", []))]
    with zipfile.ZipFile(out / "claude-export.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("conversations.json", json.dumps(convs))
        zf.writestr("users.json", "[]")

    # Gemini: Google Takeout lists one entry per prompt
    activity = [{"header": "Gemini Apps", "title": "Prompted " + line,
                 "time": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "products": ["Gemini Apps"],
                 "safeHtmlItem": [{"html": "<p>ASSISTANTWORD</p>"}]}
                for it in by.get("gemini", []) for line, when in zip(it.text.split("\n"), it.parts)]
    activity.append({"header": "Gemini Apps", "title": "Gave feedback: Good response",
                     "time": "2026-01-01T00:00:00Z", "products": ["Gemini Apps"]})
    with zipfile.ZipFile(out / "takeout-gemini.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Takeout/My Activity/Gemini Apps/MyActivity.json", json.dumps(activity))
        zf.writestr("Takeout/Chrome/History.json", '{"Browser History": []}')

    # Live capture: five chats that are also in the ChatGPT export, plus chats from another site
    rows = []
    for i, it in enumerate(by.get("chatgpt", [])[:5]):
        rows += [{"site": "chatgpt", "conv": f"g{i}", "title": it.title, "ts": int(when.timestamp() * 1000), "text": line}
                 for line, when in zip(it.text.split("\n"), it.parts)]
    for i, it in enumerate(by.get("claude", [])[:4]):
        rows += [{"site": "copilot", "conv": f"k{i}", "title": it.title, "ts": int(when.timestamp() * 1000) + 60000, "text": line}
                 for line, when in zip(it.text.split("\n"), it.parts)]
    (out / "brainplug-capture.json").write_text(
        json.dumps({"format": "brainplug-capture", "version": 1, "items": rows}), encoding="utf-8")

    # Obsidian vault
    vault = out / "MyVault"
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    (vault / ".obsidian" / "app.json").write_text("{}")
    seen: set[str] = set()
    for i, it in enumerate(by.get("obsidian", [])):
        name = it.title if it.title not in seen else f"{it.title} {i}"
        seen.add(it.title)
        links = " ".join(f"[[{l}]]" for l in it.links)
        (vault / f"{name}.md").write_text(
            f"---\ncreated: {it.created.isoformat()}\ntags: [{', '.join(it.tags)}]\n---\n# {it.title}\n\n"
            f"{it.text}\n\nSee also {links}\n", encoding="utf-8")
    (vault / "paper someone else wrote.pdf").write_bytes(tiny_pdf("OTHERWORD text that is not yours at all"))

    # The Brainplug folder inside the vault: memories saved by assistants are read; the notes
    # Brainplug exported itself (Items, Topics, the index) and the empty "About me" are not.
    brain = vault / "Brainplug"
    for sub in ("Memory", "Topics", "Items/ChatGPT"):
        (brain / sub).mkdir(parents=True, exist_ok=True)
    (brain / "Memory" / "2026-01-05 Answer style.md").write_text(
        "---\ncreated: 2026-01-05T10:00:00+00:00\nkind: preference\nsaved_by: Claude\npinned: true\n"
        "tags: [brainplug/memory, brainplug/preference]\n---\n\n# Answer style\n\n"
        "Prefers concise answers with one worked example and no preamble\n", encoding="utf-8")
    (brain / "Memory" / "2026-01-06 Old plan.md").write_text(
        "---\narchived: true\ncreated: 2026-01-06T10:00:00+00:00\n---\n\nOTHERWORD a memory that was archived and must be ignored\n",
        encoding="utf-8")
    (brain / "About me.md").write_text(
        "---\ncreated: 2026-01-01\n---\n# About me\n\n<!-- brainplug: fill this in. -->\n\n- Name:\n- What I do:\n", encoding="utf-8")
    (brain / "Brainplug.md").write_text("# Brainplug\n\nOTHERWORD an index written by the exporter\n", encoding="utf-8")
    (brain / "Topics" / "pandas.md").write_text("# pandas\n\nOTHERWORD a topic page written by the exporter\n", encoding="utf-8")
    (brain / "Items" / "ChatGPT" / "Read CSV.md").write_text("# Read CSV\n\nOTHERWORD a copy of a chat written by the exporter\n", encoding="utf-8")

    # Notion export ("Markdown & CSV"): every other page has no date property
    with zipfile.ZipFile(out / "notion-export.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for i, it in enumerate(by.get("notion", [])):
            hx = hashlib.md5(str(i).encode()).hexdigest()
            date = f"Created: {it.created.strftime('%B %d, %Y %I:%M %p')}\n" if i % 2 == 0 else ""
            zf.writestr(f"Workspace/{it.title} {hx}.md", f"# {it.title}\n\n{date}Tags: {', '.join(it.tags)}\n\n{it.text}\n")

    # Word documents (in a folder) and PDFs (passed one by one)
    docs = out / "Documents"
    docs.mkdir(exist_ok=True)
    for i, it in enumerate(by.get("word", [])):
        (docs / f"{it.title} {i}.docx").write_bytes(
            tiny_docx(it.text.split(". "), title=it.title, created=it.created.strftime("%Y-%m-%dT%H:%M:%SZ")))
    if pdf:
        for i, it in enumerate(by.get("pdf", [])):
            (out / f"paper {i}.pdf").write_bytes(tiny_pdf(it.text, title=it.title))

    # Gmail mbox: the mail you sent, plus replies from other people
    lines = []
    for i, it in enumerate(by.get("gmail", [])):
        sentences = it.text.split(". ")
        for j, when in enumerate(it.parts):
            body = sentences[j] if j < len(sentences) else it.text
            lines += [f"From {i}@x {when.strftime('%a %b %d %H:%M:%S +0000 %Y')}", f"X-GM-THRID: {1000 + i}",
                      "From: Me <me@example.com>", "To: someone@example.com",
                      f"Subject: {'Re: ' if j else ''}{it.title}", f"Date: {format_datetime(when)}",
                      'Content-Type: text/plain; charset="utf-8"', "", body, "",
                      "On Mon, 3 Mar 2025 at 12:00, Someone <someone@example.com> wrote:", "> earlier text OTHERWORD", ""]
            lines += [f"From r{i}@x {when.strftime('%a %b %d %H:%M:%S +0000 %Y')}", f"X-GM-THRID: {1000 + i}",
                      "Delivered-To: me@example.com", "From: Someone <someone@example.com>",
                      f"Subject: Re: {it.title}", f"Date: {format_datetime(when)}", "", "Reply from someone else OTHERWORD", ""]
    (out / "Sent.mbox").write_text("\n".join(lines), encoding="utf-8")

    # WhatsApp: one exported chat per person, local phone time, both sides
    chats: dict[str, list[str]] = {}
    for it in by.get("whatsapp", []):
        log = chats.setdefault(it.title, [f"1/1/24, 9:00 - Messages and calls are end-to-end encrypted."])
        sentences = it.text.split(". ")
        for j, when in enumerate(it.parts):
            local = when.astimezone(LOCAL)
            mine = (sentences[j] if j < len(sentences) else it.text) + " and I also wanted to tell you one more thing about it"
            log.append(f"{local.day}/{local.month}/{local:%y}, {local.hour}:{local:%M} - Juan: {mine}")
            log.append(f"{local.day}/{local.month}/{local:%y}, {local.hour}:{local:%M} - {it.title}: OTHERWORD sounds good")
            log.append(f"{local.day}/{local.month}/{local:%y}, {local.hour}:{local:%M} - {it.title}: <Media omitted>")
    wa = out / "WhatsApp"
    wa.mkdir(exist_ok=True)
    for person, log in chats.items():
        (wa / f"WhatsApp Chat with {person}.txt").write_text("\n".join(log) + "\n", encoding="utf-8")

    return {k: len(v) for k, v in by.items()}


if __name__ == "__main__":
    print(write_inputs(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 240))


def write_overlap(out: Path) -> None:
    """One ChatGPT chat in an export and, with newer messages, in a later live capture;
    and two folders that each hold a different note under the same name."""
    out.mkdir(parents=True, exist_ok=True)
    export = [{"id": "c7", "title": "Thesis plan", "create_time": 1735732800.0, "mapping": {
        "a": {"message": {"author": {"role": "user"}, "create_time": 1735732801.0,
                          "content": {"parts": ["outline my thesis on minimum wages and employment"]}}},
        "b": {"message": {"author": {"role": "assistant"}, "create_time": 1735732802.0,
                          "content": {"parts": ["ASSISTANTWORD an outline"]}}},
        "c": {"message": {"author": {"role": "user"}, "create_time": 1735732900.0,
                          "content": {"parts": ["add a chapter on data sources for the thesis"]}}}}}]
    (out / "conversations.json").write_text(json.dumps(export), encoding="utf-8")
    capture = {"format": "brainplug-capture", "version": 1, "items": [
        {"site": "chatgpt", "conv": "c7", "title": "Thesis plan", "ts": 1735732900500,
         "text": "add a chapter on  data sources for the thesis"},
        {"site": "chatgpt", "conv": "c7", "title": "Thesis plan", "ts": 1736000000000,
         "text": "now write the abstract of the thesis"}]}
    (out / "brainplug-capture.json").write_text(json.dumps(capture), encoding="utf-8")
    for name, text in (("A", "notes about the bakery business plan and its costs"),
                       ("B", "notes about marathon training blocks and long runs")):
        (out / name).mkdir(exist_ok=True)
        (out / name / "2025-03-05.md").write_text(f"{text}\n", encoding="utf-8")


def write_sessions(out: Path) -> dict[str, Path]:
    """A Claude Code session and a Codex session, shaped like the real logs, with invented words."""
    claude = out / "claude" / "projects" / "-home-ana-tidepool"
    codex = out / "codex" / "sessions" / "2026" / "03" / "02"
    claude.mkdir(parents=True, exist_ok=True)
    codex.mkdir(parents=True, exist_ok=True)
    sid, cwd = "5f1c2a9e-0000-4000-8000-00000000c1a0", "/home/ana/tidepool"

    def cc(kind, when, **more):
        return {"type": kind, "sessionId": sid, "cwd": cwd, "timestamp": f"2026-03-01T{when}Z", **more}
    lines = [
        {"type": "summary", "summary": "Tide pool sensor dashboard", "leafUuid": "x"},
        cc("user", "10:00:00", message={"role": "user", "content": "build a dashboard for the tide pool salinity sensors"}),
        cc("assistant", "10:00:05", message={"role": "assistant", "content": [{"type": "text", "text": "ASSISTANTWORD sure"}]}),
        cc("user", "10:00:06", message={"role": "user", "content": [{"type": "tool_result", "content": "TOOLWORD output"}]}),
        cc("user", "10:00:07", isMeta=True, message={"role": "user", "content": "[Image: METAWORD]"}),
        cc("user", "10:00:08", message={"role": "user", "content": "<command-name>/clear</command-name> COMMANDWORD"}),
        cc("user", "10:00:09", isSidechain=True, message={"role": "user", "content": "SIDECHAINWORD a subagent prompt"}),
        cc("queue-operation", "10:01:00", operation="enqueue", content="also chart the water temperature per hour"),
        cc("user", "10:02:00", message={"role": "user", "content": "also chart the water temperature per hour"}),
        cc("queue-operation", "10:03:00", operation="enqueue", content="use the key sk-proj-abcdefghijklmnopqrstuvwx1234 for the API"),
        cc("attachment", "10:04:00", attachment={"type": "queued_command", "humanTurn": True, "commandMode": "prompt",
           "origin": {"kind": "human"}, "prompt": [{"type": "image", "source": {}},
                                                  {"type": "text", "text": "the chart in this screenshot is upside down"}]}),
        cc("queue-operation", "10:04:00", operation="enqueue", content="the chart in this screenshot is upside down"),
        cc("attachment", "10:05:00", attachment={"type": "queued_command", "commandMode": "task-notification",
           "origin": {"kind": "task-notification"}, "prompt": "NOTIFYWORD a background task finished"}),
    ]
    (claude / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")

    rows = [
        {"timestamp": "2026-03-02T09:00:00Z", "type": "session_meta",
         "payload": {"id": "019c0000-aaaa-7bbb-8ccc-codex0000001", "timestamp": "2026-03-02T09:00:00Z", "cwd": "/home/ana/kelp"}},
        {"timestamp": "2026-03-02T09:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "<environment_context><cwd>/home/ana/kelp</cwd> ENVWORD</environment_context>"}]}},
        {"timestamp": "2026-03-02T09:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "write a script that counts sea urchins in the kelp survey photos"}]}},
        {"timestamp": "2026-03-02T09:00:03Z", "type": "event_msg", "payload": {"type": "user_message",
         "message": "write a script that counts sea urchins in the kelp survey photos"}},
        {"timestamp": "2026-03-02T09:00:09Z", "type": "response_item", "payload": {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "ASSISTANTWORD done"}]}},
        {"timestamp": "2026-03-02T09:00:10Z", "type": "response_item", "payload": {"type": "reasoning", "summary": []}},
    ]
    path = codex / "rollout-2026-03-02T09-00-00-019c0000-aaaa-7bbb-8ccc-codex0000001.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
    return {"claude": out / "claude", "codex": out / "codex"}
