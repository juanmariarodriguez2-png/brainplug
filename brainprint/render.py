"""Fill the HTML template with the analysis results.

The output is a single self-contained file: the data, three.js and the font are
all inlined, so it opens offline and nothing is ever sent anywhere.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE / "templates" / "viewer.html"
THREE = HERE / "vendor" / "three.module.min.js"
FONT = HERE / "vendor" / "inter-latin.woff2"


def template_html() -> str:
    """The viewer with three.js already inlined and the data still to fill in.
    The web app (docs/app) ships this file and fills it in the browser."""
    return (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__FONT__", base64.b64encode(FONT.read_bytes()).decode("ascii"))
        .replace("__THREE__", THREE.read_text(encoding="utf-8"))
    )


def render_html(payload: dict, lang: str = "en") -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Your text may contain "</script>" or "<!--" (notes about code do). Written as \u003c,
    # a "<" can never end or confuse the <script> block the data sits in.
    data = data.replace("<", "\\u003c")
    return (
        template_html()
        .replace("__LANG__", "es" if lang == "es" else "en")
        .replace("__TITLE__", html.escape(payload["meta"]["title"]))
        .replace("__DATA__", data)  # last, so your text is never scanned for placeholders
    )


def render(payload: dict, out: str | Path, lang: str = "en") -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(payload, lang), encoding="utf-8")
    return out
