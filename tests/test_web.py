"""The web app's JavaScript engine must agree with the Python package."""

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from test_new_sources import ZIP_SAFETY_CASES

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_web  # noqa: E402
from make_inputs import write_inputs, write_overlap, write_sessions  # noqa: E402

NODE = shutil.which("node")
ENV = {**os.environ, "TZ": "Europe/Madrid", "PYTHONPATH": str(ROOT)}
# On Windows the C runtime reads TZ in its own format (CET-1CEST) and misreads "Europe/Madrid" as UTC,
# so Python gets no TZ there and uses the system zone, which CI sets to the same rules (tzutil).
PY_ENV = {k: v for k, v in ENV.items() if not (sys.platform == "win32" and k == "TZ")}


def test_generated_files_are_current():
    for path, text in build_web.outputs().items():
        assert path.read_text(encoding="utf-8") == text, f"run: python scripts/build_web.py  ({path.name} is stale)"


def test_versions_agree():
    import brainplug
    engine = (ROOT / "docs" / "app" / "engine" / "analysis.js").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert f"VERSION = '{brainplug.__version__}'" in engine and manifest["version"] == brainplug.__version__
    assert f'version = "{brainplug.__version__}"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def rand_index(a: list[int], b: list[int]) -> float:
    """Adjusted Rand index: 1.0 when two groupings are the same."""
    comb = lambda n: n * (n - 1) / 2  # noqa: E731
    pairs = sum(comb(c) for c in Counter(zip(a, b)).values())
    sa, sb = sum(comb(c) for c in Counter(a).values()), sum(comb(c) for c in Counter(b).values())
    expected = sa * sb / comb(len(a))
    return (pairs - expected) / ((sa + sb) / 2 - expected)


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_javascript_engine_matches_python(tmp_path):
    folder = tmp_path / "inputs"
    write_inputs(folder, 300, pdf=False)
    inputs = sorted(str(p) for p in folder.iterdir())
    # --tz as well as TZ: Node honours TZ everywhere, Python ignores it on Windows
    subprocess.run([sys.executable, "-m", "brainplug", "build", *inputs, "--topics", "9", "--title", "Parity",
                    "--tz", ENV["TZ"], "-o", str(tmp_path / "py.html"), "--json", str(tmp_path / "py.json")],
                   check=True, env=PY_ENV, capture_output=True)
    done = subprocess.run([NODE, str(ROOT / "tests" / "js" / "run_engine.mjs"), str(folder), str(tmp_path / "js.json"),
                           "--topics", "9", "--html"], check=True, env=ENV, capture_output=True, encoding="utf-8")
    # These fixtures omit --me: Gmail and WhatsApp both have confident detections.
    assert json.loads(done.stdout)["notes"] == [
        "Gmail: kept the mail sent from me@example.com (detected; to change it, give your address in “Who you are” or with --me).",
        "WhatsApp: kept the messages written by Juan (detected from 6 chats; "
        'to change it, give your name in “Who you are” or with --me).',
    ]
    py = json.loads((tmp_path / "py.json").read_text(encoding="utf-8"))
    js = json.loads((tmp_path / "js.json").read_text(encoding="utf-8"))

    # what was read, and every number computed from it, must be identical
    assert js["numbers"] == py["numbers"]
    assert js["months"] == py["months"]
    key = lambda it: (it["d"], it["s"], it["t"], it["w"], it["n"], it["p"], it["u"], it["h"], it["x"])  # noqa: E731
    assert sorted(map(key, js["items"])) == sorted(map(key, py["items"]))
    assert "OTHERWORD" not in json.dumps(js) and "ASSISTANTWORD" not in json.dumps(js)

    # same structure, so the same viewer can draw it
    assert set(js) == set(py) and set(js["review"]) == set(py["review"])
    assert len(js["topics"]) == len(py["topics"]) == 9
    assert all(len(p) == 10 for p in js["points"]) and all(len(s) == 8 for s in js["spine"])
    assert len(js["shell"]) % 3 == 0 and abs(len(js["shell"]) - len(py["shell"])) < 1500
    assert [sum(col) for col in zip(*js["waves"])] == [sum(col) for col in zip(*py["waves"])]
    assert any(kind == 1 for *_, kind in js["edges"]) and len(js["edges"]) > 200

    # the topics are found by different code (scikit-learn vs. plain JavaScript) but must tell the same story
    order_py = {key(it): it["k"] for it in py["items"]}
    same = [(it["k"], order_py[key(it)]) for it in js["items"]]
    assert rand_index([a for a, _ in same], [b for _, b in same]) > 0.85

    html = (tmp_path / "js.html").read_text(encoding="utf-8")
    assert '<html lang="es">' in html and "__DATA__" not in html and "<title>Parity · Brainplug</title>" in html


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_javascript_private_mode_leaves_your_text_out(tmp_path):
    folder = tmp_path / "inputs"
    write_inputs(folder, 120, pdf=False)
    subprocess.run([NODE, str(ROOT / "tests" / "js" / "run_engine.mjs"), str(folder), str(tmp_path / "js.json"),
                    "--private", "--html"], check=True, env=ENV, capture_output=True)
    js = json.loads((tmp_path / "js.json").read_text(encoding="utf-8"))
    assert js["meta"]["private"] is True and js["numbers"]["longest"]["title"] is None
    assert all(it["t"] is None and it["x"] is None and it["tm"] is None for it in js["items"])
    assert all(t["terms"] == [] for t in js["topics"])  # keywords are words from your text too
    html = (tmp_path / "js.html").read_text(encoding="utf-8")
    start = html.index('<script id="bp-data"')
    data = html[start:html.index("</script>", start)]
    for title in ("Read CSV in pandas", "Weekly meal plan", "Interview answers"):  # titles from the demo data
        assert title not in data


@pytest.mark.skipif(not NODE, reason="needs Node.js")
def test_javascript_merges_and_keeps_like_python(tmp_path):
    folder = tmp_path / "inputs"
    write_overlap(folder)
    from brainplug import sources
    py = sources.load([folder / "brainplug-capture.json", folder / "conversations.json", folder / "A", folder / "B"])
    subprocess.run([NODE, str(ROOT / "tests" / "js" / "run_engine.mjs"), str(folder), str(tmp_path / "js.json"),
                    "--topics", "2"], check=True, env=ENV, capture_output=True)
    js = json.loads((tmp_path / "js.json").read_text(encoding="utf-8"))
    assert len(py) == 3 and js["numbers"]["items"] == 3
    assert js["numbers"]["words"] == sum(i.words for i in py)


@pytest.mark.skipif(not NODE, reason="needs Node.js")
def test_javascript_leaves_out_what_you_excluded(tmp_path):
    from brainplug import memory, sources
    from helpers import notes_folder
    folder = tmp_path / "inputs"
    vault = folder / "Vault"
    notes_folder(vault, 12)
    victim = next(i for i in sources.load([vault]) if i.source != "memory")
    memory.exclude(vault, item_id=victim.id, title=victim.title, by="test")
    py = sources.load([vault])
    assert victim.id not in {i.id for i in py}
    kind, _, rest = victim.id.partition(":")
    outer = {i.id for i in sources.load([folder])}  # the vault inside what you pass: ids carry its name
    assert f"{kind}:Vault/{rest}" not in outer and len(outer) == len(py)
    subprocess.run([NODE, str(ROOT / "tests" / "js" / "run_engine.mjs"), str(folder), str(tmp_path / "js.json"),
                    "--topics", "3"], check=True, env=ENV, capture_output=True)
    js = json.loads((tmp_path / "js.json").read_text(encoding="utf-8"))
    assert js["numbers"]["items"] == len(py) == 11


@pytest.mark.skipif(not NODE, reason="needs Node.js")
def test_javascript_reads_sessions_like_python(tmp_path):
    from brainplug import sources
    folder = tmp_path / "inputs"
    homes = write_sessions(tmp_path / "homes")
    (folder / "notes").mkdir(parents=True)
    (folder / "notes" / "plan.md").write_text("a plan for the tide pool survey with salinity and temperature", encoding="utf-8")
    for name, home in homes.items():  # dropped as folders, the way the web app gets them
        shutil.copytree(home, folder / name)
    py = sources.load([folder / "claude", folder / "codex", folder / "notes"])
    subprocess.run([NODE, str(ROOT / "tests" / "js" / "run_engine.mjs"), str(folder), str(tmp_path / "js.json"),
                    "--topics", "2"], check=True, env=ENV, capture_output=True)
    js = json.loads((tmp_path / "js.json").read_text(encoding="utf-8"))
    assert sorted(i.source for i in py) == ["claudecode", "codex", "notes"]
    assert js["numbers"]["items"] == 3 and js["numbers"]["words"] == sum(i.words for i in py)
    assert {s["id"] for s in js["numbers"]["sources"]} == {"claudecode", "codex", "notes"}


@pytest.mark.skipif(not NODE, reason="needs Node.js")
@pytest.mark.parametrize("case", [
    "gmail_confident", "gmail_plurality", "gmail_close", "gmail_tie", "gmail_given", "gmail_empty",
    "whatsapp_named", "whatsapp_unnamed", "whatsapp_multiple", "whatsapp_given",
])
def test_javascript_identity_notes_match_python(tmp_path, case):
    from brainplug import sources
    from test_brainplug import identity_mbox
    from test_new_sources import WHATSAPP_IOS

    me = []
    if case.startswith("gmail"):
        counts = {
            "gmail_confident": {"ana@example.com": 4, "bob@example.com": 1},
            "gmail_plurality": {"ana@example.com": 4, "bob@example.com": 3, "cat@example.com": 3},
            "gmail_close": {"ana@example.com": 5, "bob@example.com": 4},
            "gmail_tie": {"ana@example.com": 2, "bob@example.com": 2},
            "gmail_given": {"ana@example.com": 4, "bob@example.com": 1},
            "gmail_empty": {},
        }[case]
        (tmp_path / "mail.mbox").write_text(identity_mbox(counts), encoding="utf-8")
        if case == "gmail_given":
            me = ["BOB@example.com"]
    elif case == "whatsapp_multiple":
        for n, other in enumerate(["Marta", "Ana", "Dani"]):
            (tmp_path / f"chat{n}.txt").write_text(WHATSAPP_IOS.replace("Marta", other), encoding="utf-8")
    else:
        name = "WhatsApp Chat with Marta.txt" if case == "whatsapp_named" else "_chat.txt"
        (tmp_path / name).write_text(WHATSAPP_IOS, encoding="utf-8")
        if case == "whatsapp_given":
            me = ["JUAN"]
    inputs = sorted(tmp_path.iterdir())
    notes = []
    py = sources.load(inputs, me=me, notes=notes)
    done = subprocess.run([NODE, str(ROOT / "tests/js/identity.mjs"), json.dumps(me), *map(str, inputs)],
                          check=True, env=ENV, capture_output=True, encoding="utf-8", timeout=30)
    js = json.loads(done.stdout)
    assert js["notes"] == notes
    assert js["count"] == len(py)
    assert sorted(js["text"].splitlines()) == sorted(line for i in py for line in i.text.splitlines())


@pytest.mark.skipif(not NODE, reason="needs Node.js")
@pytest.mark.parametrize("case", ZIP_SAFETY_CASES)
def test_javascript_zip_safety_matches_python(tmp_path, monkeypatch, case):
    from brainplug import sources
    from test_new_sources import patch_zip_limits, zip_safety_input

    path, limits, reason, count = zip_safety_input(tmp_path, case)
    patch_zip_limits(monkeypatch, limits)
    notes = []
    py = sources.load([path, path], notes=notes)
    done = subprocess.run([NODE, str(ROOT / "tests/js/zip_safety.mjs"), str(path), json.dumps(limits)],
                          check=True, env=ENV, capture_output=True, encoding="utf-8", timeout=30)
    js = json.loads(done.stdout)
    assert js["count"] == len(py) == count
    if reason:
        assert any(reason in note and "skipped" in note for note in notes), notes
        assert any(reason in note and "skipped" in note for note in js["notes"]), js
    else:
        assert notes == js["notes"] == []
    assert "research research" not in js["text"]


@pytest.mark.skipif(not NODE, reason="needs Node.js")
def test_javascript_uses_saved_topic_names_like_python(tmp_path):
    from brainplug import analysis, memory, sources
    from helpers import notes_folder
    folder = tmp_path / "inputs"
    vault = folder / "Vault"
    notes_folder(vault, 60)
    keep: dict = {}
    analysis.analyse(sources.load([vault]), n_topics=4, keep=keep)
    memory.name_topic(vault, "Money & investing", keep["sig"][0])
    py = analysis.analyse(sources.load([vault]), n_topics=4, names=sources.topic_names_in([vault]))
    subprocess.run([NODE, str(ROOT / "tests" / "js" / "run_engine.mjs"), str(folder), str(tmp_path / "js.json"),
                    "--topics", "4"], check=True, env=ENV, capture_output=True)
    js = json.loads((tmp_path / "js.json").read_text(encoding="utf-8"))
    # the automatic names can differ a little (clustering has a tolerance between engines);
    # the saved name must land, in both, on a topic with the words it was saved with
    saved = set(keep["sig"][0])
    for payload in (py, js):
        named = [t for t in payload["topics"] if t["name"] == "Money & investing"]
        assert len(named) == 1 and set(named[0]["terms"]) & saved
