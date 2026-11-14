"""The web app's JavaScript engine must agree with the Python package."""

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_web  # noqa: E402
from make_inputs import write_inputs  # noqa: E402

NODE = shutil.which("node")
ENV = {**os.environ, "TZ": "Europe/Madrid", "PYTHONPATH": str(ROOT)}


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
    subprocess.run([sys.executable, "-m", "brainplug", "build", *inputs, "--topics", "9", "--title", "Parity",
                    "-o", str(tmp_path / "py.html"), "--json", str(tmp_path / "py.json")],
                   check=True, env=ENV, capture_output=True)
    done = subprocess.run([NODE, str(ROOT / "tests" / "js" / "run_engine.mjs"), str(folder), str(tmp_path / "js.json"),
                           "--topics", "9", "--html"], check=True, env=ENV, capture_output=True, text=True)
    assert json.loads(done.stdout)["notes"] == []
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
