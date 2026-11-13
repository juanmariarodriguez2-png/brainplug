"""Shared pieces for the browser checks: Chrome, and the site served on 127.0.0.1."""

import functools
import http.server
import os
import socketserver
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
CHROME = os.environ.get("BRAINPRINT_CHROME", "")
GPU = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def pytest_collection_modifyitems(config, items):
    reason = None
    if not CHROME or not Path(CHROME).exists():
        reason = "set BRAINPRINT_CHROME to a Chrome for Testing or Chromium binary"
    else:
        try:
            import playwright  # noqa: F401
        except ImportError:
            reason = "pip install playwright"
    if reason:
        for item in items:
            if "browser" in Path(str(item.fspath)).parts:
                item.add_marker(pytest.mark.skip(reason=reason))


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def site():
    """The docs/ folder (website and web app) on a local port."""
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(ROOT / "docs")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="session")
def chrome():
    return CHROME
