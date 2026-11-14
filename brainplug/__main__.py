"""Command line interface.

    python -m brainplug app                      # drag-and-drop in your browser
    python -m brainplug build export.zip ~/Vault Sent.mbox -o my_brain.html
    python -m brainplug sync --init export.zip ~/Vault && python -m brainplug sync --watch
    python -m brainplug brain ~/Vault            # a memory your AI can read and write
    python -m brainplug mcp --brain ~/Vault export.zip
    python -m brainplug demo --open
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__, analysis, demo
from .pipeline import Options, describe, load, local_tz, run  # noqa: F401  (re-exported)
from .render import render

INPUT_HELP = ("any mix of: ChatGPT/Claude export (.zip or conversations.json), Gemini Takeout (.zip or "
              "MyActivity.json), Obsidian vault or notes folder, Notion export .zip, Gmail .mbox, "
              "WhatsApp chat (.txt or .zip), Word and PDF files, a Brainplug capture .json")


def _renames(pairs: list[str] | None) -> dict[int, str]:
    out = {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        if not key.strip().isdigit() or not value.strip():
            raise SystemExit(f"--rename expects N=Name (got {pair!r})")
        out[int(key) - 1] = value.strip()  # people count topics from 1
    return out


def _options(args) -> Options:
    return Options(
        inputs=list(args.inputs), out=args.out, me=list(args.me or []), pdf=args.pdf, notion=args.notion,
        topics=args.topics, private=args.private, rename=_renames(args.rename), title=args.title,
        lang=args.lang, tz=args.tz, vault=args.vault, json=args.json, dataset=args.dataset,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="brainplug",
        description="A second brain for you and your AI assistants: a 3D map of everything you write and a memory they plug into.",
    )
    ap.add_argument("--version", action="version", version=f"brainplug {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("-o", "--out", default="brainplug.html", help="output HTML file")
        p.add_argument("--topics", type=int, help="number of topics (default: automatic)")
        p.add_argument("--private", action="store_true",
                       help="leave titles and text out of the HTML (safe to share)")
        p.add_argument("--rename", action="append", metavar="N=NAME",
                       help="rename topic N as listed in the terminal, e.g. --rename 2=Python")
        p.add_argument("--title", default="My Brainplug", help="title shown on the page")
        p.add_argument("--lang", choices=["en", "es"], default="en", help="page language")
        p.add_argument("--tz", help="time zone, e.g. Europe/Madrid (default: this computer's)")
        p.add_argument("--open", action="store_true", help="open the result in your browser")

    def reading(p):
        p.add_argument("--me", action="append", metavar="EMAIL_OR_NAME",
                       help="who you are: your email (Gmail) or your name as shown in WhatsApp; repeatable")
        p.add_argument("--pdf", action="store_true",
                       help="also read PDFs found inside folders and ZIPs (PDFs you pass directly always count)")
        p.add_argument("--notion", action="store_true",
                       help="also read Notion through its API, with real creation dates (set NOTION_TOKEN)")

    def extras(p):
        p.add_argument("--vault", metavar="DIR",
                       help="also write Markdown notes (topics, chats, links) into this Obsidian vault")
        p.add_argument("--json", metavar="FILE", help="also save the analysis as JSON")
        p.add_argument("--dataset", metavar="FILE",
                       help="also save your words as a redacted JSON Lines dataset (read it before sharing)")

    b = sub.add_parser("build", help="build from your own files")
    b.add_argument("inputs", nargs="*", help=INPUT_HELP)
    reading(b), extras(b), common(b)

    d = sub.add_parser("demo", help="build from synthetic demo data")
    d.add_argument("-n", type=int, default=600, help="number of fake items")
    d.add_argument("--json", metavar="FILE", help="also save the analysis as JSON")
    common(d)

    a = sub.add_parser("app", help="open the drag-and-drop app in your browser")
    a.add_argument("--port", type=int, default=8765)
    a.add_argument("--no-browser", action="store_true", help="do not open the browser")

    s = sub.add_parser("sync", help="rebuild from the inputs saved in brainplug.json; --watch keeps it up to date")
    s.add_argument("inputs", nargs="*", help="with --init: " + INPUT_HELP)
    s.add_argument("--init", action="store_true", help="save these inputs and options to brainplug.json")
    s.add_argument("--config", default="brainplug.json", help="settings file (default: ./brainplug.json)")
    s.add_argument("--watch", action="store_true", help="keep running and rebuild when something changes")
    s.add_argument("--every", type=float, default=30, metavar="SECONDS", help="how often --watch looks for changes")
    reading(s), extras(s), common(s)

    g = sub.add_parser("brain", help="set up a memory your AI assistants can read and write, inside your vault")
    g.add_argument("vault", help="your Obsidian vault, or any folder; a Brainplug/ folder is created inside")
    g.add_argument("inputs", nargs="*", help="with --context: exports to include as well")
    g.add_argument("--context", action="store_true", help="print the briefing, to paste into an assistant without MCP")
    g.add_argument("--remember", metavar="TEXT", help="save a memory yourself, from the terminal")
    g.add_argument("--kind", choices=["note", "fact", "preference", "decision", "project"], default="note")
    g.add_argument("--pin", action="store_true", help="with --remember: make it part of the briefing")
    g.add_argument("--review", action="store_true",
                   help="approve or archive the preferences assistants saved, which wait for your yes")
    g.add_argument("--lang", choices=["en", "es"], default="en", help='language of the "About me" template')
    g.add_argument("--tz", help="time zone, e.g. Europe/Madrid (default: this computer's)")
    reading(g)

    m = sub.add_parser("mcp", help="serve your brain to your AI assistants (Model Context Protocol)")
    m.add_argument("inputs", nargs="*", help=INPUT_HELP)
    m.add_argument("--brain", metavar="DIR",
                   help="your vault: it is read, and assistants can save memories in DIR/Brainplug/Memory")
    m.add_argument("--topics", type=int, help="number of topics (default: automatic)")
    m.add_argument("--tz", help="time zone, e.g. Europe/Madrid (default: this computer's)")
    m.add_argument("--no-cache", action="store_true",
                   help="do not keep the index in this computer's cache folder (slower starts)")
    reading(m)

    args = ap.parse_args(argv)

    if args.cmd == "app":
        from .app import serve
        return serve(args.port, open_browser=not args.no_browser)

    if args.cmd == "demo":
        items = demo.generate(n=args.n)
        print(describe(items))
        payload = analysis.analyse(items, tz=local_tz(args.tz), n_topics=args.topics or 9, private=args.private,
                                   rename=_renames(args.rename),
                                   title="Demo Brainplug" if args.title == "My Brainplug" else args.title)
        print(f"Found {len(payload['topics'])} topics: " + ", ".join(t["name"] for t in payload["topics"]))
        out = render(payload, args.out, lang=args.lang)
        if args.json:
            Path(args.json).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {out.resolve()}")
        if args.open:
            webbrowser.open(out.resolve().as_uri())
        return 0

    if args.cmd in ("mcp", "brain"):
        from . import memory
        from .agent import Brain, cache_file, make_server
        vault = getattr(args, "brain", None) or getattr(args, "vault", None)
        if args.cmd == "mcp" and not args.inputs and not args.notion and not vault:
            ap.error("mcp needs your vault or your files, e.g.: brainplug mcp --brain ~/Vault export.zip")
        if args.cmd == "brain" and args.remember:
            path = memory.remember(vault, args.remember, kind=args.kind, pin=args.pin, source="me")
            print(f"Saved {path.resolve()}")
            return 0
        if args.cmd == "brain" and args.review:
            return review(vault)
        log = lambda text: print(text, file=sys.stderr)  # noqa: E731  (stdout belongs to the protocol)
        inputs = list(args.inputs)
        if vault:
            base = memory.init(vault, getattr(args, "lang", "en"))
            vault = str(Path(vault).expanduser().resolve())
            if vault not in [str(Path(p).expanduser().resolve()) for p in inputs]:
                inputs.insert(0, vault)
        missing = next((p for p in inputs if not Path(p).expanduser().exists()), None)
        if missing:
            ap.error(f"Not found: {missing}")
        if args.cmd == "brain" and not args.context:
            server = ["mcp", "--brain", vault]
            print(f"Your brain lives in {base}\n"
                  f"  About me.md   a few lines about you; assistants read them at the start of a conversation\n"
                  f"  Memory/       what assistants are asked to remember, one note each\n\n"
                  f"Connect an assistant\n"
                  f"  Claude Code     claude mcp add --transport stdio brainplug -- brainplug mcp --brain \"{vault}\"\n"
                  f"  Claude Desktop  Settings > Developer > Edit Config, and add:\n"
                  f"                  {json.dumps({'mcpServers': {'brainplug': {'command': 'brainplug', 'args': server}}})}\n\n"
                  f"Add your exports after the folder to make them part of the brain:\n"
                  f"  brainplug mcp --brain \"{vault}\" chatgpt-export.zip Sent.mbox\n\n"
                  f"For an assistant without MCP, print a briefing to paste:\n"
                  f"  brainplug brain \"{vault}\" --context")
            return 0
        o = Options(inputs=inputs, me=list(args.me or []), pdf=args.pdf, notion=args.notion)
        if args.cmd == "brain":  # --context: read everything now and print the briefing
            try:
                items = load(o, log)
            except (FileNotFoundError, ValueError) as err:
                ap.error(str(err))
            log(describe(items))
            print(Brain(items, tz=local_tz(args.tz), vault=vault).context())
            return 0
        quiet = lambda text: None  # noqa: E731
        key = json.dumps({"inputs": [str(Path(p).expanduser().resolve()) for p in inputs], "me": o.me,
                          "pdf": o.pdf, "notion": o.notion, "topics": args.topics, "tz": args.tz}, sort_keys=True)
        brain = Brain(tz=local_tz(args.tz), n_topics=args.topics, vault=vault, loader=lambda: load(o, quiet),
                      watch=inputs, cache=None if args.no_cache else cache_file(key), log=log).start()
        log("Brainplug is answering; your files are read in the background"
            + (f", and memories go to {vault}" if vault else "") + ".")
        make_server(brain).run()
        return 0

    try:
        if args.cmd == "sync":
            from . import sync
            if args.init:
                if not args.inputs and not args.notion:
                    ap.error("sync --init needs your files and folders")
                path = sync.write_config(_options(args), args.config)
                print(f"Saved {path.resolve()}. Now run: brainplug sync   (or: brainplug sync --watch)")
                return 0
            if args.inputs:
                ap.error("to change the inputs, run sync --init again (or edit brainplug.json)")
            if args.watch:
                print(f"Watching the inputs in {args.config} every {args.every:g} s. Press Ctrl+C to stop.")
                try:
                    sync.watch(args.config, every=args.every)
                except KeyboardInterrupt:
                    print("\nStopped.")
                return 0
            o = sync.read_config(args.config)
        else:
            if not args.inputs and not args.notion:
                ap.error("build needs at least one file or folder (or --notion)")
            o = _options(args)
        run(o)
    except (FileNotFoundError, ValueError) as err:
        ap.error(str(err))
    if args.open:
        webbrowser.open(Path(o.out).resolve().as_uri())
    return 0


def review(vault: str) -> int:
    """Go through the preferences assistants saved, which wait for your approval."""
    from . import memory
    waiting = memory.pending(vault)
    if not waiting:
        print("Nothing waits for your approval.")
        return 0
    print(f"{len(waiting)} preference(s) saved by assistants wait for your approval. "
          "Approved ones become part of every briefing.\n")
    for m in waiting:
        print(f"{m['created'][:10]} · saved by {m['by'] or 'an assistant'} · {m['kind']}\n  "
              + " ".join(m["text"].split())[:400])
        try:
            answer = input("Approve it? [y]es / [n]o, archive it / anything else: later  ").strip().lower()
        except EOFError:
            break
        if answer.startswith(("y", "s")):  # yes / sí
            memory.approve(vault, m["name"])
            print("  approved\n")
        elif answer.startswith("n"):
            memory.forget(vault, m["name"])
            print("  archived (the note stays in your vault)\n")
        else:
            print("  left for later\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
