import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from brainplug import demo, memory, sync
from brainplug.__main__ import main
from brainplug.agent import Brain
from brainplug.export import redact
from brainplug.pipeline import Options
from helpers import notes_folder

TZ = ZoneInfo("Europe/Madrid")
ROOT = Path(__file__).resolve().parent.parent


def test_agent_tools_answer_from_your_record():
    brain = Brain(demo.generate(200), tz=TZ, n_topics=9)
    overview = brain.overview()
    assert "200 items" in overview and "Topics (biggest first)" in overview and "ChatGPT" in overview
    hits = brain.search("squat deadlift protein", limit=5).splitlines()
    assert 1 <= len(hits) <= 5 and hits[0].startswith("#")
    number = hits[0].split(" ")[0]
    page = brain.read(number)
    assert page.splitlines()[0].startswith(number) and "words" in page
    assert brain.search("zzzzqqqq") == 'Nothing found for "zzzzqqqq".'
    only_notes = brain.search("python pandas", limit=10, source="obsidian")
    assert all("· Obsidian ·" in line for line in only_notes.splitlines())
    topic = brain.topic("1")
    assert topic.startswith("Topic 1:") and "Per month:" in topic
    assert "No topic matches" in brain.topic("no-such-topic-xyz")
    assert "There is no item" in brain.read("#99999")
    year = brain.payload["numbers"]["last"][:4]
    assert "items from " + year in brain.timeline(start=year)
    assert brain.review().startswith("Last 60 days")


def test_mcp_server_round_trip(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    vault = tmp_path / "vault"
    notes_folder(vault)
    log = open(tmp_path / "server.log", "w", encoding="utf-8")  # noqa: SIM115  (closed below)

    async def talk():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "brainplug", "mcp", "--brain", str(vault), "--topics", "6"],
            env={**os.environ, "PYTHONPATH": str(ROOT), "BRAINPLUG_CACHE": str(tmp_path / "cache")})
        # pass where the server's log goes: stdio_client's default is whatever sys.stderr was when mcp was imported
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                call = lambda name, **args: session.call_tool(name, args)  # noqa: E731
                text = lambda result: result.content[0].text  # noqa: E731
                tools = [t.name for t in (await session.list_tools()).tools]
                found = text(await call("recall", query="portfolio diversification", limit=3))
                saved = text(await call("remember", text="The capstone project is about tide pools and crab behaviour",
                                        title="Capstone topic", kind="project", pin=True, saved_by="Test client"))
                again = text(await call("recall", query="capstone tide pools crab"))
                briefing = text(await call("context"))
                memory.approve(vault, next((vault / "Brainplug" / "Memory").glob("*Capstone topic.md")).stem)
                approved = text(await call("context"))
                return tools, found, saved, again, briefing, approved

    try:
        tools, found, saved, again, briefing, approved = asyncio.run(asyncio.wait_for(talk(), timeout=90))
    finally:
        log.close()
    assert tools == ["context", "recall", "remember", "read", "forget", "exclude", "overview", "topic", "timeline",
                     "review", "name_topic"]
    assert found.startswith("#") and "· Notes ·" in found
    note = vault / "Brainplug" / "Memory"
    [path] = list(note.glob("*Capstone topic.md"))
    written = path.read_text(encoding="utf-8")
    assert "kind: project" in written and "saved_by: Test client" in written
    assert re.match(r"Saved as #[a-z2-7]{6} in Brainplug/Memory/", saved) and "waits for their approval" in saved
    assert "· Memory ·" in again.splitlines()[0] and "tide pools" in again
    # an assistant's standing preference is not used until the person approves it
    assert "Keep in mind:" not in briefing and "wait for their approval" in briefing
    assert "Keep in mind:\n- The capstone project is about tide pools" in approved
    assert list((tmp_path / "cache").glob("index-*.pickle"))  # the next start reads the index from here


def test_sync_config_and_watch(tmp_path, capsys, monkeypatch):
    notes_folder(tmp_path / "vault", 40)
    monkeypatch.chdir(tmp_path)
    assert main(["sync", "--init", "vault", "-o", "out/brain.html", "--lang", "es", "--topics", "5",
                 "--rename", "1=Main", "--me", "Juan"]) == 0
    saved = json.loads((tmp_path / "brainplug.json").read_text())
    assert saved["inputs"] == [str((tmp_path / "vault").resolve())] and saved["rename"] == {"1": "Main"}
    assert main(["sync"]) == 0
    html = (tmp_path / "out" / "brain.html").read_text(encoding="utf-8")
    assert '<html lang="es">' in html and '"name":"Main"' in html

    o = sync.read_config(tmp_path / "brainplug.json")
    assert o.rename == {0: "Main"} and o.me == ["Juan"] and Path(o.out).is_absolute()
    before = sync.fingerprint(o.inputs)
    assert before == sync.fingerprint(o.inputs)
    (tmp_path / "vault" / "new idea.md").write_text("a brand new note about tide pools and crabs", encoding="utf-8")
    assert sync.fingerprint(o.inputs) != before

    builds = []
    edits = iter([None, lambda: (tmp_path / "vault" / "second.md").write_text("another note about kelp forests"), None, None])

    def fake_build(options):
        builds.append(len(list(Path(options.inputs[0]).glob("*.md"))))

    def say(_):
        step = next(edits, None)
        if step:
            step()

    # cycle 1 builds; an edit lands; the change must be seen twice (stable) before the rebuild
    real_sleep = time.sleep
    monkeypatch.setattr(time, "sleep", lambda s: (say(None), real_sleep(0))[1])
    assert sync.watch(tmp_path / "brainplug.json", every=0, say=lambda _: None, cycles=5, build=fake_build) == 2
    assert builds == [41, 42]

    (tmp_path / "bad.json").write_text('{"inputz": []}')
    with pytest.raises(ValueError):
        sync.read_config(tmp_path / "bad.json")


def test_dataset_is_redacted_and_json_dump(tmp_path, capsys):
    vault = tmp_path / "vault"
    notes_folder(vault, 30)
    (vault / "contacts.md").write_text(
        "---\ncreated: 2025-01-05\n---\nwrite to ana.lopez@example.com or call +34 612 345 678, "
        "account ES91 2100 0418 4502 0005 1332, order 9876543, see https://example.com/x and @ana_l", encoding="utf-8")
    out = tmp_path / "data" / "set.jsonl"
    assert main(["build", str(vault), "-o", str(tmp_path / "b.html"), "--dataset", str(out),
                 "--json", str(tmp_path / "b.json"), "--topics", "4"]) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 31 and set(rows[0]) == {"n", "month", "source", "kind", "topic", "words", "text"}
    text = next(r["text"] for r in rows if "[email]" in r["text"])
    for secret in ("ana.lopez", "612", "2100", "9876543", "example.com", "@ana_l"):
        assert secret not in text
    assert all(tag in text for tag in ("[email]", "[phone]", "[iban]", "[number]", "[handle]"))  # links are dropped on load
    assert redact("see https://example.com/x?y=1 now") == "see [url] now"
    payload = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert payload["numbers"]["items"] == 31 and "best effort" in capsys.readouterr().out
    assert redact("meet at 10:30 on 2025-03-04, room 12") == "meet at 10:30 on 2025-03-04, room 12"


def test_build_needs_inputs(capsys):
    with pytest.raises(SystemExit):
        main(["build"])
    assert Options().out == "brainplug.html"
