"""The web app, in a real browser, must give the same numbers as the Python package."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from conftest import GPU  # noqa: E402
from make_inputs import write_inputs  # noqa: E402


def test_web_app_matches_python_and_works_offline(site, chrome, tmp_path):
    from playwright.sync_api import sync_playwright

    folder = tmp_path / "inputs"
    write_inputs(folder, 300)
    loose = sorted(str(p) for p in folder.iterdir() if p.is_file())
    folders = sorted(str(p) for p in folder.iterdir() if p.is_dir())
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=GPU)
        page = browser.new_context(timezone_id="Europe/Madrid", locale="es-ES").new_page()
        errors, requests = [], []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.goto(f"{site}/app/")
        page.evaluate("window.__ready")  # everything the app needs has been fetched…
        assert page.inner_text("#offline") != ""
        page.context.set_offline(True)  # …so from here on it must work with no network at all
        page.set_input_files("#inFiles", loose)
        for path in folders:
            page.set_input_files("#inFolder", path)
        assert page.locator("#list li").count() == len(loose) + len(folders)
        page.click("#build")
        page.wait_for_selector("#result.on", timeout=120_000)
        web = page.evaluate("window.__brainprint.payload")
        assert page.evaluate("window.__brainprint.notes") == []
        viewer = next(f for f in page.frames if f.url.startswith("blob:"))
        viewer.wait_for_function("window.__bp && window.__bp.ready", timeout=30_000)
        html = page.evaluate("fetch(document.getElementById('download').href).then(r => r.text())")
        page.click("#back")  # a second build reuses the same worker
        page.click("#build")
        page.wait_for_selector("#result.on", timeout=120_000)
        browser.close()

    assert errors == []
    assert all(u.startswith((site + "/", "blob:", "data:")) for u in requests), "the page must not talk to any other server"
    assert '<html lang="es">' in html and "__DATA__" not in html and "ASSISTANTWORD" not in html and "OTHERWORD" not in html

    env = {**os.environ, "TZ": "Europe/Madrid", "PYTHONPATH": str(ROOT)}
    subprocess.run([sys.executable, "-m", "brainprint", "build", *loose, *folders, "-o", str(tmp_path / "py.html"),
                    "--json", str(tmp_path / "py.json")], check=True, env=env, capture_output=True)
    py = json.loads((tmp_path / "py.json").read_text(encoding="utf-8"))
    assert web["numbers"] == py["numbers"]
    assert {s["id"] for s in web["numbers"]["sources"]} == {
        "chatgpt", "claude", "gemini", "copilot", "obsidian", "notion", "word", "pdf", "gmail", "whatsapp", "memory"}
