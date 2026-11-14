import json
import threading
import zipfile
from datetime import timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from brainplug import notion_api, sources
from helpers import tiny_docx, tiny_pdf
from make_inputs import write_overlap, write_sessions

GEMINI = [
    {"header": "Gemini Apps", "title": "Prompted how do I interpret a p-value in a regression?",
     "time": "2025-03-03T10:00:00.123Z", "products": ["Gemini Apps"],
     "safeHtmlItem": [{"html": "<p>ASSISTANT ANSWER</p>"}]},
    {"header": "Gemini Apps", "title": "Prompted and what about robust standard errors?",
     "time": "2025-03-03T10:05:00Z", "products": ["Gemini Apps"]},
    {"header": "Gemini Apps", "title": "Prompted plan a weekend in Lisbon", "time": "2025-03-05T18:00:00Z",
     "products": ["Gemini Apps"]},
    {"header": "Gemini", "title": "Used Gemini Apps", "time": "2024-02-17T22:05:10Z", "products": ["Gemini Apps"],
     "titleUrl": "https://gemini.google.com/app/c/abc123def", "details": [
         {"name": "Request", "value": "explain compound interest with an example"},
         {"name": "Response", "value": "ASSISTANT ANSWER"}]},
    {"header": "Gemini Apps", "title": "Gave feedback: Good response", "time": "2025-03-05T18:01:00Z",
     "products": ["Gemini Apps"]},
    {"header": "Search", "title": "Searched for shoes", "time": "2025-03-05T18:00:00Z", "products": ["Search"]},
]

WHATSAPP_IOS = """‎[12/03/25, 21:03:15] Marta: ‎Messages and calls are end-to-end encrypted.
[12/03/25, 21:03:20] Juan: I finished the econometrics problem set, the regression with robust standard errors finally works
[12/03/25, 21:04:02] Marta: THEIR WORDS nice!
[12/03/25, 21:05:10] Juan: tomorrow I want to review heteroskedasticity and the instrumental variables chapter
before the exam, see https://example.com/notes
[13/03/25, 09:00:00] Juan: ok
[13/03/25, 09:01:00] Marta: ‎image omitted
"""

WHATSAPP_ANDROID = """3/4/25, 9:15 p. m. - Los mensajes y las llamadas están cifrados de extremo a extremo.
3/4/25, 9:15 p. m. - Dani: THEIR WORDS vienes al gimnasio?
3/4/25, 9:16 p. m. - Juan: sí, hoy toca pierna: sentadillas, prensa y peso muerto rumano, luego estiramientos largos y algo de movilidad
3/4/25, 9:17 p. m. - Juan: <Multimedia omitido>
3/4/25, 9:18 p. m. - Dani: THEIR WORDS vale
"""


def test_gemini_takeout_json_and_html(tmp_path):
    items = sources.parse_json(GEMINI)
    assert len(items) == 3 and {i.source for i in items} == {"gemini"}
    by_id = {i.id: i for i in items}
    assert by_id["gemini:abc123def"].text == "explain compound interest with an example"
    stats = next(i for i in items if "p-value" in i.text)  # two prompts 5 minutes apart: one chat
    assert len(stats.parts) == 2 and "robust standard errors" in stats.text and stats.kind == "chat"
    assert not any("ASSISTANT" in i.text or "feedback" in i.text.lower() for i in items)

    page = ('<div class="outer-cell mdl-cell"><div class="mdl-grid"><div class="header-cell"><p>Gemini Apps<br></p></div>'
            '<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">Prompted&nbsp;what is '
            'a confidence interval?<br>Mar 3, 2025, 9:30:00 PM UTC<br><p>ASSISTANT ANSWER</p></div></div></div>')
    (tmp_path / "Takeout" / "My Activity" / "Gemini Apps").mkdir(parents=True)
    (tmp_path / "Takeout" / "My Activity" / "Gemini Apps" / "MyActivity.html").write_text(page, encoding="utf-8")
    (tmp_path / "Takeout" / "other.json").write_text('{"not": "an export"}')  # ignored, no error
    [item] = sources.load([tmp_path])
    assert item.text == "what is a confidence interval?" and item.created.hour == 21


def test_capture_file_and_duplicates(tmp_path):
    capture = {"format": "brainplug-capture", "version": 1, "items": [
        {"site": "chatgpt", "conv": "c1", "title": "Pandas groupby", "ts": 1735732801000, "text": "how do I groupby in pandas?"},
        {"site": "chatgpt", "conv": "c1", "title": "Pandas groupby", "ts": 1735732901000, "text": "and how do I aggregate two columns at once?"},
        {"site": "claude", "conv": "u9", "title": "", "ts": 1735800000000, "text": "draft a cover letter for a data internship"},
    ]}
    (tmp_path / "brainplug-capture.json").write_text(json.dumps(capture))
    export = [{"id": "c1", "title": "Pandas groupby", "create_time": 1735732800.0, "mapping": {
        "b": {"message": {"author": {"role": "user"}, "create_time": 1735732801.0,
                          "content": {"parts": ["how do I groupby in pandas?"]}}}}}]
    (tmp_path / "conversations.json").write_text(json.dumps(export))
    items = sources.load([tmp_path])
    assert [i.id for i in items] == ["chatgpt:c1", "claude:u9"]
    assert len(items[0].parts) == 2  # the fuller copy of the same chat wins
    assert items[1].title.startswith("draft a cover letter")


def test_export_and_later_capture_keep_every_message(tmp_path):
    # The export knows the first message, the capture the newest one: neither may be lost.
    write_overlap(tmp_path)
    [chat] = sources.load([tmp_path / "conversations.json", tmp_path / "brainplug-capture.json"])
    assert [" ".join(m.split()) for m in chat.text.split("\n")] == [
        "outline my thesis on minimum wages and employment", "add a chapter on data sources for the thesis",
        "now write the abstract of the thesis"]
    assert len(chat.parts) == 3 and chat.title == "Thesis plan" and "ASSISTANTWORD" not in chat.text
    assert chat.created.timestamp() == 1735732800.0


def test_same_name_in_two_folders_keeps_both_notes(tmp_path):
    write_overlap(tmp_path)
    items = sources.load([tmp_path / "A", tmp_path / "B", tmp_path / "A"])  # A twice: still one copy of it
    assert sorted("bakery" in i.text for i in items) == [False, True]
    assert len({i.id for i in items}) == 2


def test_claude_code_and_codex_sessions_keep_only_what_you_typed(tmp_path, monkeypatch):
    homes = write_sessions(tmp_path)
    items = {i.source: i for i in sources.load([homes["claude"] / "projects", homes["codex"] / "sessions"])}
    claude, codex = items["claudecode"], items["codex"]
    assert claude.msgs == ["build a dashboard for the tide pool salinity sensors",
                           "also chart the water temperature per hour",  # typed while it worked: logged twice, kept once
                           "use the key [secret] for the API",  # a pasted key is masked
                           "the chart in this screenshot is upside down"]  # sent with a screenshot, logged twice
    assert claude.title == "tidepool · Tide pool sensor dashboard" and claude.id.startswith("claudecode:5f1c2a9e")
    assert codex.msgs == ["write a script that counts sea urchins in the kelp survey photos"]
    assert codex.title.startswith("kelp · write a script") and codex.created.isoformat().startswith("2026-03-02T09:00:02")
    words = " ".join(i.text for i in items.values())
    for leaked in ("ASSISTANTWORD", "TOOLWORD", "METAWORD", "COMMANDWORD", "SIDECHAINWORD", "ENVWORD", "abcdefghij",
                   "NOTIFYWORD"):
        assert leaked not in words

    # --sessions finds both folders where the tools keep them
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(homes["claude"]))
    monkeypatch.setenv("CODEX_HOME", str(homes["codex"]))
    assert sources.session_folders() == [homes["claude"] / "projects", homes["codex"] / "sessions"]
    from brainplug.pipeline import Options, load
    assert {i.source for i in load(Options(sessions=True), say=lambda _: None)} == {"claudecode", "codex"}


def test_session_prompts_that_start_with_markup_are_kept():
    assert sources._typed('<div class="card"> why does this not center?').startswith("<div")
    assert sources._typed("<environment_context><cwd>/x</cwd></environment_context>") == ""
    assert sources._typed("<command-name>/clear</command-name>") == ""


def test_whatsapp_keeps_only_my_messages(tmp_path):
    (tmp_path / "WhatsApp Chat with Marta.txt").write_text(WHATSAPP_IOS, encoding="utf-8")
    notes: list[str] = []
    items = sources.load([tmp_path], notes=notes)
    assert len(items) == 1  # 13 March has too little text to count
    assert notes == [
        "WhatsApp: kept the messages written by Juan (detected from the file name; "
        'to change it, give your name in “Who you are” or with --me).']
    item = items[0]
    assert (item.source, item.kind, item.title, item.size) == ("whatsapp", "message", "Marta", 3)
    assert "instrumental variables chapter\nbefore the exam" in item.text
    assert "THEIR WORDS" not in item.text and "encrypted" not in item.text and "http" not in item.text
    assert (item.created.day, item.created.month, item.created.hour, len(item.parts)) == (12, 3, 21, 2)

    # two chats: you are the person who is in both; 12-hour clock, day first
    with zipfile.ZipFile(tmp_path / "WhatsApp Chat - Dani.zip", "w") as zf:
        zf.writestr("_chat.txt", WHATSAPP_ANDROID)
    notes.clear()
    items = sources.load([tmp_path], notes=notes)
    assert notes == [
        "WhatsApp: kept the messages written by Juan (detected from 2 chats; "
        'to change it, give your name in “Who you are” or with --me).']
    gym = next(i for i in items if "sentadillas" in i.text)
    assert gym.title == "Dani" and (gym.created.day, gym.created.month, gym.created.hour) == (3, 4, 21)
    assert "THEIR WORDS" not in gym.text and "omitido" not in gym.text


def test_whatsapp_needs_to_know_who_you_are(tmp_path):
    (tmp_path / "_chat.txt").write_text(WHATSAPP_IOS, encoding="utf-8")
    notes: list[str] = []
    assert sources.load([tmp_path], notes=notes) == [] and "Juan" in notes[0] and "Marta" in notes[0]
    assert len(notes) == 1 and "unsure:" in notes[0] and '“Who you are” or with --me' in notes[0]
    notes.clear()
    [item] = sources.load([tmp_path], me=["juan"], notes=notes)
    assert notes == []
    assert "THEIR WORDS" not in item.text


def test_whatsapp_detects_identity_across_unnamed_chats(tmp_path):
    for n, other in enumerate(["Marta", "Ana", "Dani"]):
        (tmp_path / f"chat{n}.txt").write_text(WHATSAPP_IOS.replace("Marta", other), encoding="utf-8")
    notes = []
    assert len(sources.load([tmp_path], notes=notes)) == 3
    assert notes == [
        "WhatsApp: kept the messages written by Juan (detected from 3 chats; "
        'to change it, give your name in “Who you are” or with --me).']


def test_word_and_pdf(tmp_path):
    (tmp_path / "essay.docx").write_bytes(tiny_docx(
        ["Inflation expectations &amp; central bank credibility", "A short essay on monetary policy."],
        title="Monetary policy essay"))
    (tmp_path / "~$essay.docx").write_bytes(b"lock file")
    (tmp_path / "thesis.pdf").write_bytes(tiny_pdf("Chapter one reviews the literature on minimum wages"))
    [doc] = sources.load([tmp_path])  # PDFs inside a folder are skipped unless asked for
    assert (doc.source, doc.kind, doc.title) == ("word", "note", "Monetary policy essay")
    assert doc.text.startswith("Inflation expectations & central bank") and doc.created.year == 2025
    both = sources.load([tmp_path], pdf=True)
    pdf = next(i for i in both if i.source == "pdf")
    assert pdf.title == "My thesis draft" and "minimum wages" in pdf.text
    assert (pdf.created.year, pdf.created.month) == (2025, 3)
    assert len(sources.load([tmp_path / "thesis.pdf"])) == 1  # a PDF you pass yourself always counts


def test_dates_with_seconds_and_12_hour_clock():
    assert sources.parse_date("Mar 3, 2025, 10:00:00 PM UTC").hour == 22
    assert sources.parse_date("3 mar 2025, 12:30:00 AM").hour == 0
    assert sources.parse_date("March 3, 2025 10:00 AM").hour == 10


def test_notion_api_gives_real_dates():
    calls = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, code, body, headers=None):
            data = json.dumps(body).encode()
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("search", body.get("start_cursor"), self.headers["Authorization"], self.headers["Notion-Version"]))
            if len(calls) == 1:
                return self._json(429, {}, {"Retry-After": "0"})  # rate limited once
            if not body.get("start_cursor"):
                return self._json(200, {"has_more": True, "next_cursor": "p2", "results": [
                    {"id": "aaaa-1111", "created_time": "2024-05-06T08:00:00.000Z", "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "Reading list"}]},
                        "Tags": {"type": "multi_select", "multi_select": [{"name": "books"}]}}}]})
            return self._json(200, {"has_more": False, "results": [
                {"id": "bbbb-2222", "created_time": "2025-01-02T08:00:00.000Z", "archived": True, "properties": {}},
                {"id": "cccc-3333", "created_time": "2025-02-03T08:00:00.000Z", "properties": {
                    "title": {"type": "title", "title": [{"plain_text": "Empty page"}]}}}]})

        def do_GET(self):
            if "aaaa-1111" in self.path:
                return self._json(200, {"has_more": False, "results": [
                    {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Books to read this summer"}]}},
                    {"id": "b2", "type": "toggle", "has_children": True, "toggle": {"rich_text": [{"plain_text": "Economics"}]}},
                    {"id": "b3", "type": "child_page", "child_page": {"title": "Another page"}}]})
            if "/b2/" in self.path:
                return self._json(200, {"has_more": False, "results": [
                    {"id": "b4", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Poor Economics"}]}}]})
            return self._json(200, {"has_more": False, "results": []})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        [page] = notion_api.load_notion("secret_x", base=f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
    assert (page.id, page.title, page.tags, page.dated) == ("notion:aaaa1111", "Reading list", ["books"], True)
    assert page.created.astimezone(timezone.utc).strftime("%Y-%m-%d") == "2024-05-06"
    assert page.text == "Books to read this summer Economics Poor Economics"
    assert calls[1][2:] == ("Bearer secret_x", "2022-06-28") and calls[2][1] == "p2"
    with pytest.raises(notion_api.NotionError):
        notion_api.load_notion("")


ZIP_SAFETY_LIMITS = {
    "depth": 2, "entries": 6, "ratioMinBytes": 128, "ratio": 10,
    "bytes": 100_000, "directoryBytes": 100_000,
}
ZIP_SAFETY_CASES = [
    "normal", "chatgpt", "zip64", "declared-partial", "unsupported", "ratio", "depth", "declared-stored",
    "declared-deflated", "entries", "nested-entries", "budget", "nested-budget", "directory", "forged-count",
]


def zip_safety_input(tmp_path, case):
    """Small hostile fixtures shared by the Python and Node tests."""
    import io
    import struct
    import zlib

    text = b"My research plan compares sea water temperature and salinity in the tide pools."
    limits = dict(ZIP_SAFETY_LIMITS)

    def archive(entries, compression=zipfile.ZIP_DEFLATED):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=compression) as zf:
            for name, data in entries:
                zf.writestr(name, data)
        return buf.getvalue()

    reason, count = "", 1
    data = archive([("plan.md", text)])
    if case == "chatgpt":
        export = [{"id": "safe", "title": "Research", "create_time": 1735732800, "mapping": {
            "m": {"message": {"author": {"role": "user"}, "content": {"parts": [text.decode()]}}}}}]
        data = archive([("conversations.json", json.dumps(export))])
    elif case == "zip64":
        # A small ZIP with a real ZIP64 directory trailer, as used by big exports.
        eocd = bytearray(data[-22:])
        cd_size, cd_offset = struct.unpack_from("<II", eocd, 12)
        record_at = len(data) - 22
        record = struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, 1, 1, cd_size, cd_offset)
        locator = struct.pack("<IIQI", 0x07064B50, 0, record_at, 1)
        struct.pack_into("<HHII", eocd, 8, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
        data = data[:-22] + record + locator + eocd
    elif case == "unsupported":
        data = archive([("plan.md", text)], zipfile.ZIP_BZIP2)
        reason, count = "unsupported", 0
    elif case == "ratio":
        data = archive([("bomb.txt", b"research " * 1024), ("plan.md", text)])
        reason = "compression ratio"
    elif case == "depth":
        data = archive([("middle.zip", archive([("inner.zip", data)])), ("plan.md", text)])
        reason = "nesting depth"
    elif case.startswith("declared-"):
        # Forge both the size and a valid CRC for the declared prefix. A reader
        # that silently truncates at the declared size would accept this entry.
        payload = b"research " * 1024
        declared = 4096 if case == "declared-partial" else 32
        if case == "declared-partial":
            limits["ratioMinBytes"] = 100_000  # exercise the streaming check
        compression = zipfile.ZIP_STORED if case.endswith("stored") else zipfile.ZIP_DEFLATED
        bad = bytearray(archive([("bomb.txt", payload)], compression))
        cd = bad.index(b"PK\x01\x02")
        for crc_at, size_at in ((14, 22), (cd + 16, cd + 24)):
            struct.pack_into("<I", bad, crc_at, zlib.crc32(payload[:declared]))
            struct.pack_into("<I", bad, size_at, declared)
        # Keep a good sibling to prove one bad entry doesn't stop the archive.
        data = archive([("bad.zip", bad), ("plan.md", text)], zipfile.ZIP_STORED)
        reason = "declared size"
    elif case in ("entries", "forged-count"):
        data = archive([(f"ignored{i}.bin", b"") for i in range(7)])
        if case == "forged-count":
            bad = bytearray(data)
            eocd = bad.index(b"PK\x05\x06")
            struct.pack_into("<HH", bad, eocd + 8, 1, 1)
            data = bytes(bad)
        reason, count = "entry count", 0
    elif case == "nested-entries":
        inner = archive([(f"ignored{i}.bin", b"") for i in range(5)] + [("plan.md", text)])
        data = archive([("inner.zip", inner)])
        reason, count = "entry count", 0
    elif case == "budget":
        limits["bytes"] = len(text)
        data = archive([("a.md", text), ("b.md", text)])
        reason = "byte budget"
    elif case == "nested-budget":
        inner = archive([("plan.md", text)])
        limits["bytes"] = len(inner) + len(text) - 1
        data = archive([("inner.zip", inner)])
        reason, count = "byte budget", 0
    elif case == "directory":
        limits["directoryBytes"] = 46
        reason, count = "central directory", 0
    path = tmp_path / "export.zip"
    path.write_bytes(data)
    return path, limits, reason, count


def patch_zip_limits(monkeypatch, limits):
    for key, name in {"depth": "MAX_ZIP_DEPTH", "entries": "MAX_ZIP_ENTRIES", "ratioMinBytes": "ZIP_RATIO_MIN_BYTES",
                      "ratio": "MAX_ZIP_RATIO", "bytes": "MAX_ZIP_BYTES", "directoryBytes": "MAX_ZIP_DIRECTORY_BYTES"}.items():
        monkeypatch.setattr(sources, name, limits[key])


@pytest.mark.parametrize("case", ZIP_SAFETY_CASES)
def test_zip_safety_limits(tmp_path, monkeypatch, case):
    path, limits, reason, count = zip_safety_input(tmp_path, case)
    patch_zip_limits(monkeypatch, limits)
    monkeypatch.setattr(sources, "ZIP_COPY_CHUNK", 1024)
    notes = []
    items = sources.load([path], notes=notes)
    assert len(items) == count
    if reason:
        assert any(reason in note and "skipped" in note for note in notes), notes
    else:
        assert notes == []
    assert all("research research" not in item.text for item in items)


def test_zip_budgets_reset_between_top_level_inputs(tmp_path, monkeypatch):
    path, limits, _, _ = zip_safety_input(tmp_path, "normal")
    limits["entries"] = 1
    limits["bytes"] = 80
    patch_zip_limits(monkeypatch, limits)
    notes = []
    assert len(sources.load([path, path], notes=notes)) == 1  # duplicate items merge
    assert notes == []
