# Contributing

Start with [README.md](README.md). Use invented data in tests and examples;
never add personal exports.

## Architecture

The Python package is in `brainplug/`:

| File | Responsibility |
| --- | --- |
| `sources.py` | Parse exports, notes and captures into common `Item` objects. |
| `analysis.py` | Find topics, connections, layouts, review insights and statistics. |
| `brain.py` | Build brain and galaxy geometry. |
| `render.py` | Fill the shared viewer template to produce offline HTML. |
| `pipeline.py` | Load, analyse and write the requested outputs. |
| `sync.py` | Save input settings and rebuild when files change. |
| `memory.py` | Manage the person's Markdown memories and approvals. |
| `agent.py` | Run the Model Context Protocol (MCP) server. |
| `app.py` | Serve the local drag-and-drop app on this computer. |
| `export.py` | Write Obsidian notes and redacted datasets. |
| `notion_api.py` | Read Notion pages through its API. |

In `docs/app/`, `index.html` handles the page and files; `worker.js` runs analysis
off the main thread. `docs/app/engine/` is the JavaScript port.

Both engines use `brainplug/templates/viewer.html`. `scripts/build_web.py`
copies it with bundled assets into `docs/app/viewer.tpl.html` and renders
`docs/demo.html` and `docs/demo_es.html` from it when given `--demo`.
Edit the original template, then regenerate.

`extension/` captures messages the person sends, stores them in the browser and
passes them to the web app or saves them as a capture file.

## Decision: keep two engines

Python supports local tools and larger inputs; JavaScript runs entirely in a
browser tab. Parsing and analysis exist in both and must give the same numbers.
`tests/test_web.py` runs JavaScript in Node and compares it with Python: counts
and parsed items match exactly; topic clustering allows a tolerance.

The MCP server, memory management, sync, Notion API access, local app and exports
are Python-only and stay so. The browser can read memory notes and download its
HTML result; it does not need those Python services ported.

When changing a parser or analysis, change both engines and extend the parity
tests in `tests/test_web.py`. Geometry changes belong in both `brainplug/brain.py`
and `docs/app/engine/brain.js` too.

Run `python scripts/build_web.py` after changing the viewer template, its bundled
assets, `brainplug/render.py`'s template assembly or `brainplug/stopwords.py`.
It refreshes the browser template and `docs/app/engine/stopwords.js`;
`test_generated_files_are_current` fails if those outputs are stale.
Use `python scripts/build_web.py --demo` to refresh the demos after viewer or
engine changes. The script does not translate Python parsers or analysis.

## Principles to preserve

- Keep only the person's own words, excluding assistant answers, tool output and
  other people's messages. Word and PDF files are read whole; users supply their own.
- Nothing is uploaded by Brainplug. Keep processing local and the viewer usable
  offline. Optional Notion API reads go directly to Notion; material an assistant
  reads through MCP goes to that assistant's model.
- Private mode must leak no titles, excerpts or keywords, including in embedded
  data. Topic names remain visible, so the person must be able to rename them.
- Memories are plain Markdown the person owns. Save only what they said or
  confirmed. Standing preferences from assistants wait for their approval before
  entering the briefing.
- MCP item codes must stay stable when inputs change. Preserve item identities
  and the code generation in `brainplug/agent.py`.

## Checks

From the repository root, with Python 3.10 or later and Node.js (CI uses Node 22):

```bash
pip install -e ".[dev]"
pip install ruff
python -m pytest -q
ruff check .
```

Ruff reads `ruff.toml`. Browser tests need Playwright and `BRAINPLUG_CHROME`
pointing to a Chrome or Chromium executable; follow
[tests/browser/README.md](tests/browser/README.md), then run
`python -m pytest -q tests/browser`. They skip without that setup; JavaScript
parity tests skip without Node.

[.github/workflows/tests.yml](.github/workflows/tests.yml) runs pytest with
Node 22 on Linux (Python 3.10 and 3.13), macOS and Windows (Python 3.13), then
builds a demo. Separate Linux jobs run browser tests with Playwright Chromium
and reject skips, and run `python -m ruff check .`.

## Broken exports and new sources

Use the export-format issue template for broken or unsupported exports. Include
the app, export option, file names and sizes, expected result and error. Share
the shape, not private contents: replace names, IDs, addresses, titles and text
with invented values. Keep field names, nesting, types and date formats. Redact
sensitive file names, preserving extensions and folder layout. Never attach the
original export.

To add a source, put its parser and format detection in `brainplug/sources.py`
and `docs/app/engine/sources.js`, returning the common item fields in each.
Check folder and ZIP filtering if needed. Add invented inputs to
`tests/make_inputs.py`, parser tests under `tests/`, and parity coverage in
`tests/test_web.py`, including checks that other people's words stay out.
Add the source ID and display name to `SOURCE_NAMES` in both
`brainplug/analysis.py` and `docs/app/engine/analysis.js`, then update the supported
sources in `README.md`.
