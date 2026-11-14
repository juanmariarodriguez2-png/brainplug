"""The web app, in a real browser, must give the same numbers as the Python package."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from conftest import GPU  # noqa: E402
from make_inputs import write_inputs  # noqa: E402


@pytest.mark.parametrize("lang,title,requested,paths,waits", [
    ("en", "Request your exports now", "Requested",
     ["Data controls › Export data", "Privacy › Export data", "My Activity › Gemini Apps", "Mail › select only the Sent label"],
     ["minutes to hours", "hours to days"]),
    ("es", "Solicita ya tus exportaciones", "Solicitada",
     ["Controles de datos › Exportar datos", "Privacidad › Exportar datos", "Mi actividad › Aplicaciones de Gemini", "Correo › selecciona solo la etiqueta Enviados"],
     ["minutos o unas horas", "horas y varios días"]),
])
def test_export_checklist_languages_and_persistence(site, chrome, lang, title, requested, paths, waits):
    from playwright.sync_api import expect, sync_playwright

    services = ["ChatGPT", "Claude", "Gemini", "Gmail"]
    urls = ["https://chatgpt.com/#settings/DataControls", "https://claude.ai/settings",
            "https://takeout.google.com/", "https://takeout.google.com/"]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=GPU)
        page = browser.new_page()
        page.goto(f"{site}/app/?lang={lang}")
        expect(page.locator("#requestsTitle")).to_have_text(title)
        rows = page.locator("#requests li")
        expect(rows).to_have_count(4)
        for i, (service, url, path) in enumerate(zip(services, urls, paths)):
            row = rows.nth(i)
            expect(row.locator("a")).to_have_text(service)
            expect(row.locator("a")).to_have_attribute("href", url)
            expect(row.locator("a")).to_have_attribute("target", "_blank")
            assert "noopener" in row.locator("a").get_attribute("rel").split()
            expect(row.locator(".what")).to_contain_text(path)
            expect(row.locator("small")).to_contain_text(waits[i // 2])
            expect(row.get_by_role("checkbox")).to_have_accessible_name(f"{requested} · {service}")
            expect(row.get_by_role("checkbox")).not_to_be_checked()
        expect(rows.nth(2)).to_contain_text("JSON")
        for source in ["Obsidian", "Word/PDF", "WhatsApp"]:
            expect(page.locator("#startNow")).to_contain_text(source)
        # Keep the existing guide, and update the new copy with the live language switch.
        expect(page.locator("#export li")).to_have_count(9)
        page.locator("#requestedChatgpt").check()
        page.locator("#requestedGemini").check()
        page.click("#lang")
        expect(page.locator("#requestsTitle")).to_have_text(
            "Solicita ya tus exportaciones" if lang == "en" else "Request your exports now")
        expect(page.locator("#remind")).to_have_text("Recordármelo" if lang == "en" else "Remind me")
        expect(page.locator("#requestedChatgpt")).to_be_checked()
        page.reload()
        expect(page.locator("#requestedChatgpt")).to_be_checked()
        expect(page.locator("#requestedGemini")).to_be_checked()
        expect(page.locator("#requestedClaude")).not_to_be_checked()
        page.locator("#requestedChatgpt").uncheck()
        page.reload()
        expect(page.locator("#requestedChatgpt")).not_to_be_checked()
        expect(page.locator("#requestedGemini")).to_be_checked()
        browser.close()


@pytest.mark.parametrize("lang,zone,instant", [
    ("en", "Europe/Madrid", "2026-03-28T22:30:00+00:00"),  # tomorrow changes to summer time
    ("es", "America/Los_Angeles", "2027-01-01T07:30:00+00:00"),  # locally still 31 December
])
def test_export_reminder_download_offline(site, chrome, lang, zone, instant):
    from playwright.sync_api import sync_playwright

    now = datetime.fromisoformat(instant)
    tomorrow = (now.astimezone(ZoneInfo(zone)) + timedelta(days=1)).replace(hour=10, minute=0, second=0)
    utc = lambda date: date.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=GPU)
        page = browser.new_page(timezone_id=zone)
        page.clock.install(time=now)
        page.goto(f"{site}/app/?lang={lang}")
        page.evaluate("window.__ready")
        requests = []
        page.on("request", lambda r: requests.append(r.url))
        page.context.set_offline(True)
        with page.expect_download() as download:
            page.click("#remind")
        assert download.value.suggested_filename.endswith(".ics")
        calendar = Path(download.value.path()).read_bytes()
        assert calendar.startswith(b"BEGIN:VCALENDAR\r\n")
        assert calendar.endswith(b"END:VEVENT\r\nEND:VCALENDAR\r\n")
        assert b"\n" not in calendar.replace(b"\r\n", b"")
        assert all(len(line) <= 75 for line in calendar.split(b"\r\n"))
        fields = dict(line.split(":", 1) for line in calendar.decode("utf-8").split("\r\n") if ":" in line)
        assert fields["VERSION"] == "2.0"
        assert fields["UID"].endswith("@brainplug.app")
        datetime.strptime(fields["DTSTAMP"], "%Y%m%dT%H%M%SZ")
        assert fields["DTSTART"] == utc(tomorrow)
        assert fields["DTEND"] == utc(tomorrow + timedelta(minutes=30))
        assert fields["SUMMARY"] == {"en": "Brainplug: drop your exports", "es": "Brainplug: añade tus exportaciones"}[lang]
        assert "https://brainplug.app/app/" in fields["DESCRIPTION"]
        assert fields["URL"] == "https://brainplug.app/app/"
        assert all(url.startswith("blob:") for url in requests)
        browser.close()


def test_export_checklist_works_without_storage(site, chrome):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=GPU)
        page = browser.new_page()
        page.add_init_script("""Object.defineProperty(window, 'localStorage', {
            get() { throw new DOMException('Storage disabled', 'SecurityError'); }
        });""")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{site}/app/?lang=en")
        page.evaluate("window.__ready")
        page.locator("#requestedChatgpt").check()
        expect(page.locator("#requestedChatgpt")).to_be_checked()
        page.locator("#requestedChatgpt").uncheck()
        page.click("#lang")
        expect(page.locator("#remind")).to_have_text("Recordármelo")
        with page.expect_download():
            page.click("#remind")
        assert not errors
        browser.close()


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
        web = page.evaluate("window.__brainplug.payload")
        assert page.evaluate("window.__brainplug.notes") == []
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
    subprocess.run([sys.executable, "-m", "brainplug", "build", *loose, *folders, "-o", str(tmp_path / "py.html"),
                    "--json", str(tmp_path / "py.json")], check=True, env=env, capture_output=True)
    py = json.loads((tmp_path / "py.json").read_text(encoding="utf-8"))
    assert web["numbers"] == py["numbers"]
    assert {s["id"] for s in web["numbers"]["sources"]} == {
        "chatgpt", "claude", "gemini", "copilot", "obsidian", "notion", "word", "pdf", "gmail", "whatsapp", "memory"}
