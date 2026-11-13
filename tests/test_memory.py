"""The memory an assistant can read and write: plain notes in your vault."""

import json
from zoneinfo import ZoneInfo

from brainplug import memory, sources
from brainplug.__main__ import main
from brainplug.agent import Brain
from helpers import notes_folder

TZ = ZoneInfo("Europe/Madrid")


def test_memories_are_ordinary_notes(tmp_path):
    vault = tmp_path / "Vault"
    base = memory.init(vault, "es")
    assert (base / "About me.md").read_text(encoding="utf-8").startswith("---\ncreated:") and (base / "Memory").is_dir()
    assert memory.profile(vault) == ""  # the template has not been filled in

    a = memory.remember(vault, "I prefer short answers,  in Spanish", kind="preference", pin=True, source="Claude Desktop",
                        tags=["Style", "#answers", "  "])
    b = memory.remember(vault, "Line one\nLine two", title="../../etc/passwd: a <bad> title?", kind="nonsense")
    c = memory.remember(vault, "Line one\nLine two", title="../../etc/passwd: a <bad> title?")
    assert a.parent == b.parent == c.parent == base / "Memory" and len({a, b, c}) == 3  # nothing escapes, nothing is overwritten
    assert all(ch not in b.name for ch in '/\\:<>?') and c.stem.endswith(" 2")
    text = a.read_text(encoding="utf-8")
    assert "kind: preference" in text and "saved_by: Claude Desktop" in text and "pinned: true" in text
    assert "tags: [brainplug/memory, brainplug/preference, style, answers]" in text
    assert text.rstrip().endswith("I prefer short answers, in Spanish") and "\n# " not in text  # named after its own words
    assert "kind: note" in b.read_text(encoding="utf-8") and "# etc passwd a bad title" in b.read_text(encoding="utf-8")

    listed = memory.memories(vault)
    assert len(listed) == 3 and sum(m["pinned"] for m in listed) == 1 and listed[0]["text"]
    assert memory.forget(vault, b.stem) == b and "archived: true" in b.read_text(encoding="utf-8")
    assert b.exists() and len(memory.memories(vault)) == 2  # archived, not deleted
    assert memory.forget(vault, "no such note") is None and memory.forget(vault, "../About me") is None

    (base / "About me.md").write_text("---\ncreated: 2026-01-01\n---\n# About me\n\n<!-- brainplug: fill this in. -->\n\n"
                                      "- Name: Ada\n- What I do:\n- How I like answers: brief\n", encoding="utf-8")
    assert memory.profile(vault) == "# About me\n- Name: Ada\n- How I like answers: brief"


def test_loader_reads_memories_and_not_its_own_export(tmp_path, capsys):
    vault = tmp_path / "Vault"
    notes_folder(vault, 40)
    memory.init(vault)
    kept = memory.remember(vault, "The thesis deadline moved to the first week of June", kind="fact")
    gone = memory.remember(vault, "An old plan that no longer applies to anything")
    memory.forget(vault, gone.stem)
    first = sources.load([vault])
    assert len(first) == 41 and [i.title for i in first if i.source == "memory"] == [kept.stem]

    # writing the Obsidian export into the same vault must not feed it back in as new notes
    assert main(["build", str(vault), "--vault", str(vault), "-o", str(tmp_path / "b.html"), "--topics", "4"]) == 0
    assert (vault / "Brainplug" / "Topics").is_dir() and (vault / "Brainplug" / "Brainplug.md").exists()
    again = sources.load([vault])
    assert sorted(i.id for i in again) == sorted(i.id for i in first)
    assert len(sources.load([tmp_path])) == 41  # also when the vault is a sub-folder of what you pass


def test_brain_starts_empty_and_learns(tmp_path):
    vault = tmp_path / "Vault"
    memory.init(vault)
    load = lambda: sources.load([vault])  # noqa: E731
    brain = Brain(load(), tz=TZ, vault=vault, loader=load, watch=[str(vault)])
    assert '"About me" note is still empty' in brain.context() and "0 items" in brain.context()
    assert brain.recall("anything") == 'Nothing found for "anything".' and "not enough" in brain.overview()

    assert brain.remember("I prefer short answers in Spanish", kind="preference", pin=True, source="Claude").startswith("Saved as #1")
    brain.remember("PayPeek beta opens to CUNEF students first", title="PayPeek beta plan", kind="decision", tags=["paypeek"])
    brain.remember("The drone uses an ESP32 flight controller", kind="project")
    brain.remember("My thesis is about minimum wages and youth employment")
    assert brain.remember("   ") == "There is nothing to remember: the text is empty."
    hit = brain.recall("paypeek beta").splitlines()[0]
    assert hit.startswith("#2 ·") and "PayPeek beta plan" in hit
    assert "minimum wages" in brain.read("#4") and "tags: paypeek" in brain.read("#2")
    briefing = brain.context()
    assert "Keep in mind:\n- I prefer short answers in Spanish" in briefing and "Recent memories:" in briefing

    assert brain.forget("#2").startswith("Archived") and brain.recall("paypeek beta") == 'Nothing found for "paypeek beta".'
    assert "There is no item" in brain.read("#2") and "There is no item" in brain.forget("#99")

    # a note you write yourself in Obsidian is picked up, and your own notes cannot be archived by an assistant
    (vault / "Reading list.md").write_text("Books about behavioural economics and nudges to read this summer", encoding="utf-8")
    assert brain.refresh(force=True) and "Reading list" in brain.recall("behavioural economics nudges")
    mine = brain.recall("behavioural economics").split(" ")[0]
    assert "Only memories saved through `remember`" in brain.forget(mine) and (vault / "Reading list.md").exists()
    assert len(list((vault / "Brainplug" / "Memory").glob("*.md"))) == 4  # the archived note is still a file

    read_only = Brain(load(), tz=TZ)
    assert "read-only" in read_only.remember("something") and "remember(" not in read_only.context()


def test_context_is_a_short_briefing_of_a_big_record(tmp_path):
    vault = tmp_path / "Vault"
    notes_folder(vault, 150)
    base = memory.init(vault)
    (base / "About me.md").write_text("# About me\n\n- Name: Ada\n- What I do: economics student who codes\n", encoding="utf-8")
    memory.remember(vault, "Always answer in British English", kind="preference")
    for n in range(12):
        memory.remember(vault, f"Decision number {n} about the internship search and the interview calendar", kind="decision")
    brain = Brain(sources.load([vault]), tz=TZ, n_topics=8, vault=vault)
    briefing = brain.context()
    assert briefing.startswith("About them (their own note):\n# About me\n- Name: Ada")
    assert "Keep in mind:\n- Always answer in British English" in briefing
    assert "Writing about lately" in briefing and "All topics:" in briefing and briefing.count("Decision number") == 6
    assert len(briefing) < 2100 < sum(len(i.text) for i in brain.items) / 10  # a small part of what the brain holds
    assert len(brain.context(max_chars=400)) <= 600
    assert "164 items" in brain.overview() and "Memory 14" in brain.overview()


def test_brain_command(tmp_path, capsys):
    vault = tmp_path / "My Vault"
    assert main(["brain", str(vault), "--lang", "es"]) == 0
    out = capsys.readouterr().out
    assert "# Sobre mí" in (vault / "Brainplug" / "About me.md").read_text(encoding="utf-8")
    config = json.loads(next(line for line in out.splitlines() if '"mcpServers"' in line))
    assert config["mcpServers"]["brainplug"]["args"] == ["mcp", "--brain", str(vault.resolve())]
    assert main(["brain", str(vault), "--remember", "Prefiero respuestas cortas", "--kind", "preference", "--pin"]) == 0
    assert main(["brain", str(vault), "--context"]) == 0
    assert "Keep in mind:\n- Prefiero respuestas cortas" in capsys.readouterr().out
