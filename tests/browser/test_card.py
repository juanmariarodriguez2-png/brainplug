"""The offline viewer exports a shareable PNG without exporting item text."""

import json
import re
import struct
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import GPU

ROOT = Path(__file__).resolve().parents[2]
DATA_SCRIPT = re.compile(r'(<script id="bp-data" type="application/json">)(.*?)(</script>)', re.S)
SPY = """() => {
  window.cardText = [];
  const original = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function(text, ...args) {
    if (this.canvas.id === 'yearCard') window.cardText.push(String(text));
    return original.call(this, text, ...args);
  };
}"""


@pytest.mark.parametrize("lang", ["en", "es"])
def test_demo_card_png_offline(site, chrome, tmp_path, lang):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=GPU)
        context = browser.new_context(reduced_motion="reduce", viewport={"width": 390, "height": 844})
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.add_init_script(f"({SPY})()")
        # Exercise capability detection without depending on OS clipboard access.
        page.add_init_script("""Object.defineProperty(navigator, 'clipboard', {value: {
          write: async items => {
            const blob = await items[0].getType('image/png');
            const bitmap = await createImageBitmap(blob);
            window.copiedImage = [blob.type, bitmap.width, bitmap.height];
            bitmap.close();
          }
        }});""" if lang == "en" else "Object.defineProperty(window, 'ClipboardItem', {value: undefined});")
        page.goto(f"{site}/{'demo.html' if lang == 'en' else 'demo_es.html'}")
        page.wait_for_function("window.__bp?.ready")
        context.set_offline(True)
        page.on("request", lambda r: requests.append(r.url))
        page.click('#tabs button[data-view="numbers"]')
        page.click("#shareCardOpen")
        expect(page.locator("#downloadCard")).to_be_enabled()
        expect(page.locator("#showTopicNames")).to_be_checked()
        expect(page.locator("#shareCardTitle")).to_have_text("Your year with AI" if lang == "en" else "Tu año con la IA")
        with page.expect_download() as download:
            page.click("#downloadCard")
        result = download.value
        payload = page.eval_on_selector("#bp-data", "el => JSON.parse(el.textContent)")
        year = max(it["d"][:4] for it in payload["items"] if not it["u"])
        assert result.suggested_filename == f"brainplug-{year}.png"
        output = tmp_path / result.suggested_filename
        result.save_as(output)
        png = output.read_bytes()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", png[16:24]) == (1080, 1350)
        drawn = page.evaluate("window.cardText")
        assert "brainplug.app" in drawn
        assert not set(drawn) & {it[field] for it in payload["items"] for field in ("t", "x") if it[field]}
        assert not set(drawn) & {term for it in payload["items"] for term in (it["tm"] or [])}
        # A coloured scene must survive the WebGL snapshot and dark overlay.
        assert page.eval_on_selector("#yearCard", """c => {
          const p = c.getContext('2d').getImageData(0, 300, 1080, 400).data;
          let count = 0;
          for (let i = 0; i < p.length; i += 4)
            if (Math.max(p[i], p[i+1], p[i+2]) - Math.min(p[i], p[i+1], p[i+2]) > 15) count++;
          return count > 100;
        }""")
        if lang == "en":
            page.click("#copyCard")
            page.wait_for_function("window.copiedImage")
            assert page.evaluate("window.copiedImage") == ["image/png", 1080, 1350]
            page.evaluate("() => { navigator.clipboard.write = async () => { throw new Error('denied'); }; }")
            page.click("#copyCard")
            expect(page.locator("#cardStatus")).to_contain_text("Download the PNG instead")
        else:
            expect(page.locator("#copyCard")).to_be_hidden()
        page.keyboard.press("Escape")
        expect(page.locator("#shareCard")).not_to_be_visible()
        expect(page.locator("#shareCardOpen")).to_be_focused()
        assert requests == []
        assert errors == []
        browser.close()


@pytest.mark.parametrize("latest_count,private", [(20, False), (19, True)])
def test_card_year_scope_and_topic_privacy(site, chrome, latest_count, private):
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "docs/demo.html").read_text(encoding="utf-8")
    payload = json.loads(DATA_SCRIPT.search(html)[2])
    items = payload["items"]
    payload["meta"]["private"] = private
    source_a, source_b = [s["id"] for s in payload["numbers"]["sources"][:2]]
    for i, it in enumerate(items):
        it.update(d="2023-01-01", h=4, w=1, u=0, k=0,
                  t="TITLE_SECRET", x="EXCERPT_SECRET", tm=["KEYWORD_SECRET"])
        payload["points"][i][9] = 1  # note
    for i in range(latest_count):
        items[i].update(d=(date(2024, 3, 25) + timedelta(days=i)).isoformat(),
                        h=17, w=11 + i, k=i % 3, s=source_a if i < 12 else source_b)
        payload["points"][i][9] = 0 if i < 10 else 1
    # An undated item with a later placeholder date must not choose the year.
    items[-1].update(d="2099-01-01", h=23, u=1, w=2)
    for k, topic in enumerate(payload["topics"]):
        topic["name"] = f"SENSITIVE_TOPIC_{k}"
    html = DATA_SCRIPT.sub(lambda m: m[1] + json.dumps(payload) + m[3], html)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=GPU)
        page = browser.new_page(timezone_id="Europe/Madrid")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route(f"{site}/demo.html", lambda route: route.fulfill(body=html, content_type="text/html"))
        page.add_init_script(f"({SPY})()")
        page.goto(f"{site}/demo.html")
        page.wait_for_function("window.__bp?.ready")
        # UI filters must not change the period's aggregate counts.
        page.fill("#q", "NO_MATCH")
        page.click('#tabs button[data-view="numbers"]')
        page.click("#shareCardOpen")
        expect(page.locator("#downloadCard")).to_be_enabled()
        drawn = page.evaluate("window.cardText")
        # the card names its year; when that year has little in it, the span of years it covers
        assert ("2024" if latest_count == 20 else "2023–2024") in drawn and "2099" not in drawn
        assert not {"TITLE_SECRET", "EXCERPT_SECRET", "KEYWORD_SECRET"} & set(drawn)
        assert "155" in drawn  # words from ten chats; notes are excluded
        if latest_count == 20:
            assert {"20", "410", "Apr 2024", "17:00", "20 days in a row", "35%", "30%"} <= set(drawn)
            assert "All time" not in drawn
            expect(page.locator("#showTopicNames")).to_be_checked()
            assert "SENSITIVE_TOPIC_0" in drawn
        else:
            assert {"All time", str(len(items)), "4".zfill(2) + ":00", "19 days in a row", "Jan 2023"} <= set(drawn)
            assert str(sum(it["w"] for it in items)) in drawn
            expect(page.locator("#showTopicNames")).not_to_be_checked()
            assert not any("SENSITIVE_TOPIC" in t for t in drawn)
        page.evaluate("window.cardText = []")
        page.locator("#showTopicNames").set_checked(private)
        drawn = page.evaluate("window.cardText")
        assert any("SENSITIVE_TOPIC" in t for t in drawn) == private
        assert errors == []
        browser.close()
