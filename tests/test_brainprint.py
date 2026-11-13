import json
import re
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from brainprint import analysis, app, brain, demo, sources
from brainprint.__main__ import main
from brainprint.export import export_vault
from brainprint.render import render

TZ = ZoneInfo("Europe/Madrid")
HEX = "0123456789abcdef0123456789abcdef"

CHATGPT = [{
    "id": "c1", "title": "Pandas groupby", "create_time": 1735732800.0,
    "mapping": {
        "root": {"message": None},
        "a": {"message": {"author": {"role": "system"}, "create_time": 1735732800.0,
                          "content": {"content_type": "text", "parts": ["sys"]}}},
        "b": {"message": {"author": {"role": "user"}, "create_time": 1735732801.0,
                          "content": {"content_type": "text", "parts": ["how do I groupby in pandas?"]}}},
        "c": {"message": {"author": {"role": "assistant"}, "create_time": 1735732805.0,
                          "content": {"content_type": "text", "parts": ["Use df.groupby()."]}}},
    },
}]

CLAUDE = [{
    "uuid": "u1", "name": "Trip to Lisbon", "created_at": "2025-03-01T10:00:00Z",
    "chat_messages": [
        {"sender": "human", "text": "", "created_at": "2025-03-01T10:00:00Z",
         "content": [{"type": "text", "text": "plan 3 days in Lisbon"}]},
        {"sender": "assistant", "text": "Day 1: Alfama...", "created_at": "2025-03-01T10:00:09Z"},
    ],
}]

MBOX = """From 1@x Mon Mar 03 10:00:00 +0000 2025
X-GM-THRID: 111
From: Juan <juan@example.com>
To: ana@example.com
Subject: Internship application
Date: Mon, 3 Mar 2025 10:00:00 +0000
Content-Type: text/plain; charset="utf-8"

Hello Ana, I would like to apply for the summer internship in data analysis.

--
Juan SIGNATURE

From 2@x Mon Mar 03 12:00:00 +0000 2025
X-GM-THRID: 111
Delivered-To: juan@example.com
From: Ana <ana@example.com>
To: juan@example.com
Subject: Re: Internship application
Date: Mon, 3 Mar 2025 12:00:00 +0000

Thanks Juan, send me your CV. SECRETWORD

From 3@x Mon Mar 03 13:00:00 +0000 2025
X-GM-THRID: 111
From: Juan <juan@example.com>
To: ana@example.com
Subject: Re: Internship application
Date: Mon, 3 Mar 2025 13:00:00 +0000

Here is my CV attached, thank you very much.

On Mon, 3 Mar 2025 at 12:00, Ana <ana@example.com> wrote:
> Thanks Juan, send me your CV. SECRETWORD

From 4@x Tue Mar 04 09:00:00 +0000 2025
Delivered-To: juan@example.com
From: Newsletter <news@shop.com>
Subject: Big sale
Date: Tue, 4 Mar 2025 09:00:00 +0000

Buy now NEWSLETTERWORD

From 5@x Tue Mar 04 10:00:00 +0000 2025
Delivered-To: juan@example.com
From: Newsletter <news@shop.com>
Subject: Another sale
Date: Tue, 4 Mar 2025 10:00:00 +0000

Buy again

From 6@x Wed Mar 05 10:00:00 +0000 2025
From: Juan <juan@example.com>
To: luis@example.com
Subject: Weekend plan
Date: Wed, 5 Mar 2025 10:00:00 +0000
Content-Type: text/html; charset="utf-8"

<div>Shall we go hiking on Saturday morning?</div><blockquote>old quoted HTMLQUOTE</blockquote>
"""


# ------------------------------------------------------------------ sources
def test_parse_chatgpt():
    (item,) = sources.parse_chatgpt(CHATGPT)
    assert (item.source, item.kind, item.title) == ("chatgpt", "chat", "Pandas groupby")
    assert item.text == "how do I groupby in pandas?"  # only your side
    assert item.size == 2 and len(item.parts) == 1  # system message dropped


def test_parse_claude_uses_content_blocks():
    (item,) = sources.parse_claude(CLAUDE)
    assert item.source == "claude" and item.text == "plan 3 days in Lisbon"


def test_parse_date_formats():
    assert sources.parse_date("2025-03-03T10:00:00Z").hour == 10
    assert sources.parse_date("March 3, 2025 4:30 PM") == datetime(2025, 3, 3, 16, 30, tzinfo=timezone.utc)
    assert sources.parse_date("3 de marzo de 2025").month == 3
    assert sources.parse_date("03/04/2025").month == 4  # day first
    assert sources.parse_date("not a date") is None


def test_obsidian_vault(tmp_path):
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "old.md").write_text("deleted note with enough words")
    (vault / "Projects").mkdir()
    (vault / "Projects" / "Thesis idea.md").write_text(
        "---\ncreated: 2025-02-01\ntags:\n  - thesis\n---\n# Idea\nStudy internships and wages, see "
        "[[Reading list|my list]] #economics\n```python\nSECRETCODE = 1\n```\n")
    (vault / "Reading list.md").write_text("Books about labour economics and data science")
    (vault / "2025-03-05.md").write_text("Daily note: talked about the thesis with my tutor")
    (vault / "photo.png").write_bytes(b"\x89PNG")
    items = {i.title: i for i in sources.load([vault])}
    assert set(items) == {"Thesis idea", "Reading list", "2025-03-05"}
    thesis = items["Thesis idea"]
    assert thesis.source == "obsidian" and thesis.kind == "note"
    assert thesis.created.strftime("%Y-%m-%d") == "2025-02-01"
    assert thesis.links == ["Reading list"] and set(thesis.tags) == {"thesis", "economics"}
    assert "SECRETCODE" not in thesis.text and "my list" in thesis.text
    assert items["2025-03-05"].created.strftime("%Y-%m-%d") == "2025-03-05"


def test_notion_export_zip(tmp_path):
    z = tmp_path / "notion.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(f"Export/Project Plan {HEX}.md",
                    "# Project Plan\n\nCreated: March 3, 2025 10:00 AM\nTags: work, plan\n\n"
                    f"Launch the website next month. See [Other page](Other%20page%20{HEX[::-1]}.md)")
        zf.writestr(f"Export/Other page {HEX[::-1]}.md", "# Other page\n\nSome loose thoughts about pricing")
        zf.writestr("Export/database.csv", "a,b\n1,2\n")
    items = {i.title: i for i in sources.load([z])}
    plan = items["Project Plan"]
    assert plan.source == "notion" and plan.dated
    assert plan.created == datetime(2025, 3, 3, 10, 0, tzinfo=timezone.utc)
    assert plan.tags == ["plan", "work"] and plan.links == ["Other page"]
    assert not items["Other page"].dated  # no date property: flagged, not invented


def test_gmail_keeps_only_what_you_wrote(tmp_path):
    box = tmp_path / "All mail.mbox"
    box.write_text(MBOX)
    items = {i.title: i for i in sources.load([box])}  # your address is detected
    assert set(items) == {"Internship application", "Weekend plan"}
    thread = items["Internship application"]
    assert (thread.source, thread.kind, len(thread.parts)) == ("gmail", "message", 2)
    assert "apply for the summer internship" in thread.text and "Here is my CV" in thread.text
    for leaked in ("SECRETWORD", "SIGNATURE", "NEWSLETTERWORD", "wrote:"):
        assert leaked not in thread.text
    assert items["Weekend plan"].text == "Shall we go hiking on Saturday morning?"


def test_load_mixed_inputs_and_unknown_format(tmp_path):
    z = tmp_path / "claude.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("conversations.json", json.dumps(CLAUDE))
        zf.writestr("users.json", "[]")
    j = tmp_path / "conversations.json"
    j.write_text(json.dumps(CHATGPT))
    assert [i.source for i in sources.load([z, j])] == ["chatgpt", "claude"]  # oldest first
    with pytest.raises(ValueError):
        sources.parse_json([{"foo": 1}])
    with pytest.raises(FileNotFoundError):
        sources.load([tmp_path / "missing.zip"])


# ----------------------------------------------------------------- analysis
def test_layouts_and_connections():
    items = demo.generate(n=220)
    payload = analysis.analyse(items, TZ)
    pts = np.array(payload["points"])
    assert brain.inside_cerebrum(pts[:, :3]).all()  # brain layout stays inside the brain
    radius = np.hypot(pts[:, 3], pts[:, 5])
    assert np.isfinite(pts).all() and radius.max() < brain.GALAXY_RADIUS + 0.6
    assert ((pts[:, 8] >= 0) & (pts[:, 8] <= 1)).all()
    n = len(items)
    assert payload["edges"] and all(0 <= a < b < n for a, b, _, _ in payload["edges"])
    assert any(kind == 1 for *_, kind in payload["edges"])  # explicit note links survive
    assert sum(t["count"] for t in payload["topics"]) == n == len(payload["items"])
    counts = [t["count"] for t in payload["topics"]]
    assert counts == sorted(counts, reverse=True)
    assert sum(map(sum, payload["waves"])) == n
    assert {"rising", "fading", "dormant", "bridges", "cross", "deep", "year_ago"} <= set(payload["review"])


def test_undated_items_do_not_distort_time():
    items = demo.generate(n=80)
    for item in items[:10]:
        item.dated = False
    payload = analysis.analyse(items, TZ, n_topics=5)
    assert payload["numbers"]["undated"] == 10
    assert sum(map(sum, payload["waves"])) == 70
    assert sum(i["u"] for i in payload["items"]) == 10


def test_private_mode_hides_titles_and_text(tmp_path):
    items = demo.generate(n=80)
    payload = analysis.analyse(items, TZ, private=True)
    assert all(i["t"] is None and i["x"] is None and i["tm"] is None for i in payload["items"])
    assert payload["numbers"]["longest"]["title"] is None
    page = render(payload, tmp_path / "p.html").read_text(encoding="utf-8")
    assert all(f'"t":"{i.title}"' not in page for i in items[:20])


def test_render_is_self_contained(tmp_path):
    items = demo.generate(n=60)
    items[0].title = "</script><b>x</b>"
    payload = analysis.analyse(items, TZ, rename={0: "Python"})
    page = render(payload, tmp_path / "x.html", lang="es").read_text(encoding="utf-8")
    assert page.count("</script>") == 3  # data, three.js, app: the title cannot close a tag early
    start = page.index('<script id="bp-data"')
    block = page[page.index(">", start) + 1:page.index("</script>", start)]
    assert "<" not in block and "\\u003c/script>" in block  # nor can "<!--" or "<script" confuse the parser
    assert 'lang="es"' in page and payload["topics"][0]["name"] == "Python"
    # our own code loads nothing from the internet (three.js is inlined and excluded here)
    ours = re.sub(r'<script id="three-src".*?</script>', "", page, flags=re.S)
    assert re.findall(r'(?:src|href)=["\']https?://|fetch\(|XMLHttpRequest', ours) == []


# ------------------------------------------------------------ export and app
def test_export_vault(tmp_path):
    items = demo.generate(n=90)
    payload = analysis.analyse(items, TZ, n_topics=5)
    written = export_vault(items, payload, tmp_path)
    base = tmp_path / "Brainprint"
    assert (base / "Brainprint.md").exists() and len(list((base / "Topics").glob("*.md"))) == 5
    chats = list((base / "Items" / "ChatGPT").glob("*.md"))
    assert chats and "## What I wrote" in chats[0].read_text(encoding="utf-8")
    assert not (base / "Items" / "Obsidian").exists()  # vault notes are linked, never copied
    assert written == len(list(base.rglob("*.md")))


def test_app_roundtrip_and_token():
    server, state = app.start(port=8911)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(url + "/")  # no token: refused
        assert denied.value.code == 403

        def call(path, method, body=b""):
            req = urllib.request.Request(url + path, data=body, method=method,
                                         headers={"X-Brainprint-Token": state.token})
            return urllib.request.urlopen(req).read()

        convs = []
        for n in range(6):
            conv = json.loads(json.dumps(CHATGPT[0]))
            conv["id"], conv["title"] = f"c{n}", f"Topic {n % 2} question {n}"
            convs.append(conv)
        call("/upload?name=../../evil/conversations.json", "PUT", json.dumps(convs).encode())
        assert (state.uploads / "evil" / "conversations.json").exists()  # stays inside uploads
        result = json.loads(call("/build", "POST", json.dumps({"title": "T", "private": True}).encode()))
        assert result["ok"] and result["items"] == 6
        assert b"bp-data" in urllib.request.urlopen(f"{url}/result?t={state.token}").read()
    finally:
        server.shutdown()
        server.server_close()
        state.close()


def test_safe_relative():
    assert str(app.safe_relative("../../etc/passwd")) == "etc/passwd"
    assert str(app.safe_relative("C:\\Users\\x\\note.md")) == "C_/Users/x/note.md"
    assert app.safe_relative("../..") is None


def test_cli_demo(tmp_path, capsys):
    out = tmp_path / "demo.html"
    assert main(["demo", "-n", "120", "-o", str(out), "--lang", "es"]) == 0
    assert out.stat().st_size > 500_000 and "Found 9 topics" in capsys.readouterr().out
