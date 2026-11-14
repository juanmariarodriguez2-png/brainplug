# Changelog

## 0.4.0 — 2026-11-14

### Memory for your assistants (MCP server)
- Answers at once: files are read in the background, and the index is kept in this
  computer's cache folder so the next start loads it (25,000 items: first answer in a
  millisecond instead of 25 s, next start in 0.2 s). `--no-cache` turns it off.
- Items have codes that stay the same when files change (`#k3f9a2`), instead of positions.
- Standing preferences saved by an assistant wait for your approval (`pinned: pending`);
  `brainplug brain VAULT --review` approves or archives them.
- `recall(order="oldest")` finds when you first raised something.
- `remember(replaces=…)` corrects a memory and archives the old one, linked both ways.
- `exclude` leaves an item or a whole source out (`Brainplug/Excluded.md`).
- `name_topic` saves clearer topic names in `Brainplug/Topic names.md`, recognised by the topic's
  words after it is recomputed, and used by built maps too (private ones included).
- `brainplug brain VAULT --draft-about` drafts your "About me" note from your writing.
- Read-only tools are marked as such, so assistants can run them without asking.
- `brainplug connect` adds Brainplug to Claude Desktop, Claude Code, Codex, Cursor,
  Windsurf, Gemini CLI, VS Code and LM Studio with an absolute command and a backup;
  `brainplug doctor` checks everything, including a real MCP handshake.

- The MCP SDK is a regular dependency now, so `uvx brainplug mcp --brain VAULT` works as is
  (`brainplug[agent]` still installs). `server.json` describes Brainplug for the official MCP registry.

### Sources
- `--sessions`: what you typed to Claude Code and Codex (never the agent's work; pasted
  keys masked as `[secret]`).
- The same chat in an export and a later capture is merged message by message instead of
  keeping only the longer copy; notes with the same name in two folders are both kept.
- The detected Gmail address and WhatsApp name are shown, marked "unsure" when the evidence is weak.
- ZIP files cannot exhaust disk or memory (depth, entries, compression ratio and size
  budgets; forged sizes are caught).

### Privacy
- `--private` no longer keeps topic keywords in the file.
- The browser extension keeps only messages you send, never drafts (new chat, clear…).
- A privacy policy page: https://brainplug.app/privacy.html

### Website and app
- The app says what works at once and offers a checklist to request each export, with a
  calendar reminder.
- Numbers › Share: a "Your year with AI" image to post, with no titles or text on it.

### Project
- CI on Linux, macOS and Windows, browser tests that really run, ruff.
- Windows: `tzdata` is installed so `--tz` works.
- Ready for PyPI (trusted publishing on release), Chrome Web Store kit (`STORE.md`,
  `scripts/package_extension.py`), `CONTRIBUTING.md`.

## 0.3.0 — 2026-11-13
- First public version.
