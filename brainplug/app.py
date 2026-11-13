"""A tiny local web app: drop your files in the browser, get your brainplug.

It listens only on this computer (127.0.0.1) and needs a secret token that is
part of the URL it opens, so no other website or device can talk to it.
Nothing is uploaded anywhere: "uploading" just copies files to a temp folder.
"""

from __future__ import annotations

import atexit
import json
import secrets
import shutil
import signal
import sys
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

from . import analysis, sources
from .render import render_html

PAGE = Path(__file__).parent / "templates" / "app.html"
CHUNK = 1 << 20


class State:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(18)
        self.dir = Path(tempfile.mkdtemp(prefix="brainplug_app_"))
        self.uploads = self.dir / "uploads"
        self.uploads.mkdir()
        self.result: str | None = None

    def reset(self) -> None:
        shutil.rmtree(self.uploads, ignore_errors=True)
        self.uploads.mkdir()

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def safe_relative(name: str) -> PurePosixPath | None:
    """Turn an uploaded file name into a path that cannot escape the upload folder."""
    parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts if p not in ("/", "..", ".", "")]
    parts = [p.replace(":", "_") for p in parts]
    return PurePosixPath(*parts) if parts else None


def build(state: State, options: dict) -> dict:
    inputs = sorted(state.uploads.iterdir())
    inputs += [Path(p.strip().strip('"')) for p in options.get("paths") or [] if p.strip()]
    if not inputs:
        raise ValueError("Add at least one file or folder first.")
    me = [a.strip() for a in str(options.get("me") or "").split(",") if a.strip()]
    notes: list[str] = []
    items = sources.load(inputs, me=me or None, pdf=bool(options.get("pdf")), notes=notes)
    from .pipeline import local_tz
    payload = analysis.analyse(
        items, tz=local_tz(), n_topics=int(options["topics"]) if options.get("topics") else None,
        private=bool(options.get("private")), title=str(options.get("title") or "My Brainplug"),
    )
    state.result = render_html(payload, lang=str(options.get("lang") or "en"))
    return {
        "ok": True, "items": len(items), "notes": notes,
        "sources": payload["numbers"]["sources"],
        "topics": [{"name": t["name"], "count": t["count"]} for t in payload["topics"]],
    }


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Brainplug"

        def log_message(self, *args) -> None:  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes | str, ctype: str = "application/json", extra: dict | None = None):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self, query: dict) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            token = self.headers.get("X-Brainplug-Token") or (query.get("t") or [""])[0]
            return host in ("127.0.0.1", "localhost") and secrets.compare_digest(token, state.token)

        def _route(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if not self._allowed(query):
                self._send(403, json.dumps({"ok": False, "error": "Forbidden"}))
                return None, None
            return url.path, query

        def do_GET(self):
            path, query = self._route()
            if path == "/":
                self._send(200, PAGE.read_text(encoding="utf-8").replace("__TOKEN__", state.token), "text/html")
            elif path == "/result" and state.result:
                extra = {"Content-Disposition": 'attachment; filename="brainplug.html"'} if "download" in query else None
                self._send(200, state.result, "text/html", extra)
            elif path is not None:
                self._send(404, json.dumps({"ok": False, "error": "Not found"}))

        def do_PUT(self):
            path, query = self._route()
            if path != "/upload":
                if path is not None:
                    self._send(404, json.dumps({"ok": False, "error": "Not found"}))
                return
            rel = safe_relative((query.get("name") or [""])[0])
            length = self.headers.get("Content-Length")
            if rel is None or length is None:
                self._send(400, json.dumps({"ok": False, "error": "Bad upload"}))
                return
            target = state.uploads / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            left = int(length)
            with open(target, "wb") as fh:
                while left > 0:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        break
                    fh.write(chunk)
                    left -= len(chunk)
            self._send(200, json.dumps({"ok": True}))

        def do_POST(self):
            path, _ = self._route()
            if path is None:
                return
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if path == "/reset":
                state.reset()
                self._send(200, json.dumps({"ok": True}))
            elif path == "/build":
                try:
                    self._send(200, json.dumps(build(state, json.loads(raw or b"{}"))))
                except Exception as err:  # show the reason in the page instead of a stack trace
                    self._send(200, json.dumps({"ok": False, "error": str(err) or type(err).__name__}))
            else:
                self._send(404, json.dumps({"ok": False, "error": "Not found"}))

    return Handler


def start(port: int = 8765) -> tuple[ThreadingHTTPServer, State]:
    state = State()
    last: Exception | None = None
    for candidate in range(port, port + 20):
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), make_handler(state)), state
        except OSError as err:
            last = err
    state.close()
    raise OSError(f"No free port between {port} and {port + 19}") from last


def serve(port: int = 8765, open_browser: bool = True) -> int:
    server, state = start(port)
    atexit.register(state.close)  # also clean up when the terminal window is simply closed
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={state.token}"
    print(f"Brainplug is running on this computer only:\n\n  {url}\n\nPress Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Temporary copies deleted.")
    finally:
        server.server_close()
        state.close()
    return 0
