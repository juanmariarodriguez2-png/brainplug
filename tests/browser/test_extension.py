"""The capture extension, loaded into Chrome, against stand-in pages on the real addresses."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EXT = str(ROOT / "extension")

# A stand-in chat page: a message box, a send button, and a "new chat" that only gets
# its address and title a moment after the first message, like the real sites.
MOCK = """<!doctype html><title>%(title)s</title><body><div id=log></div>
%(box)s <button id=send aria-label="Send">send</button> <button id=other>attach</button>
<script>
const box = document.getElementById('box'); let n = 0;
const read = () => box.tagName === 'TEXTAREA' ? box.value : box.innerText;
const clear = () => { if (box.tagName === 'TEXTAREA') box.value = ''; else box.innerHTML = '<p><br></p>'; };
function submit() {
  const text = read().trim(); if (!text) return;
  document.getElementById('log').insertAdjacentHTML('beforeend', '<div class=user></div><div>ASSISTANT ANSWER that must never be stored</div>');
  [...document.querySelectorAll('#log .user')].pop().textContent = text;
  clear();
  if (!n++) setTimeout(() => { history.pushState({}, '', '%(path)s'); document.title = '%(named)s'; }, 800);
}
box.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.shiftKey) return;
  e.preventDefault();
  if (window.menuOpen) { window.menuOpen = false; if (box.tagName === 'TEXTAREA') box.value += ' @picked'; return; }
  submit();
});
document.getElementById('send').onclick = submit;
</script>"""
EDITABLE = '<div id=box contenteditable="true"><p><br></p></div>'
TEXTAREA = '<textarea id=box></textarea>'
PAGES = {
    "https://chatgpt.com/": dict(title="ChatGPT", box=EDITABLE, path="/c/6f1e2d3c-aaaa-4bbb-8ccc-1234567890ab", named="Regression help - ChatGPT"),
    "https://claude.ai/new": dict(title="Claude", box=EDITABLE, path="/chat/0a1b2c3d-eeee-4fff-9000-abcdefabcdef", named="Cover letter draft - Claude"),
    "https://gemini.google.com/app": dict(title="Gemini", box=TEXTAREA, path="/app/9f8e7d6c5b4a", named="Gemini"),
    "https://www.perplexity.ai/": dict(title="Perplexity", box=TEXTAREA, path="/search/trip-plan-Xy12ab34cd", named="trip plan | Perplexity"),
}
STORED = "chrome.storage.local.get(null).then(g => Object.keys(g).filter(k => k.startsWith('m:')).sort().flatMap(k => g[k]))"


def test_extension_keeps_only_what_you_send(site, chrome, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(tmp_path / "profile"), executable_path=chrome, headless=True, locale="en-GB",
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
        for url, spec in PAGES.items():
            def answer(body):
                return lambda route: route.fulfill(status=200, content_type="text/html", body=body)
            ctx.route(f"https://{url.split('/')[2]}/**", answer(MOCK % spec))
        worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15_000)
        ext_id = worker.url.split("/")[2]

        def chat(url):
            page = ctx.new_page()
            page.goto(url)
            page.click("#box")
            return page

        gpt = chat("https://chatgpt.com/")  # Enter in a rich-text box; Shift+Enter is a line break, not a send
        gpt.keyboard.type("how do I interpret the coefficients of a logistic regression")
        gpt.keyboard.press("Shift+Enter")
        gpt.keyboard.type("and what changes if I standardise the variables first")
        gpt.keyboard.press("Enter")
        gpt.wait_for_timeout(1500)
        gpt.click("#box")
        gpt.keyboard.type("show me how to plot the predicted probabilities")
        gpt.keyboard.press("Enter")
        claude = chat("https://claude.ai/new")  # the send button; other buttons do not count
        claude.keyboard.type("draft a cover letter for a summer internship in data analysis")
        claude.click("#other")
        claude.wait_for_timeout(1400)
        claude.click("#send")
        gemini = chat("https://gemini.google.com/app")  # Enter that picks a suggestion is not a send
        gemini.keyboard.type("compare index funds and ETFs for a long term portfolio")
        gemini.evaluate("window.menuOpen = true")
        gemini.keyboard.press("Enter")
        gemini.wait_for_timeout(1500)
        gemini.keyboard.type(" please")
        gemini.keyboard.press("Enter")
        pplx = chat("https://www.perplexity.ai/")
        pplx.keyboard.type("plan a five day interrail route through northern Italy on a student budget")
        pplx.keyboard.press("Enter")
        pplx.wait_for_timeout(5500)  # the address and the title of a new chat settle a moment later

        popup = ctx.new_page()
        popup.goto(f"chrome-extension://{ext_id}/popup.html")
        popup.wait_for_timeout(400)
        rows = popup.evaluate(STORED)
        assert [(r["site"], r["conv"], r["title"]) for r in rows] == [
            ("chatgpt", "6f1e2d3c-aaaa-4bbb-8ccc-1234567890ab", "Regression help"),
            ("chatgpt", "6f1e2d3c-aaaa-4bbb-8ccc-1234567890ab", "Regression help"),
            ("claude", "0a1b2c3d-eeee-4fff-9000-abcdefabcdef", "Cover letter draft"),
            ("gemini", "9f8e7d6c5b4a", ""),
            ("perplexity", "trip-plan-Xy12ab34cd", "trip plan"),
        ]
        assert rows[0]["text"] == ("how do I interpret the coefficients of a logistic regression\n"
                                   "and what changes if I standardise the variables first")
        assert rows[3]["text"].endswith("@picked please") and "ASSISTANT" not in json.dumps(rows)
        assert popup.inner_text("#say") == "5 messages saved"

        popup.uncheck("#on")  # paused: nothing new is kept
        popup.wait_for_timeout(300)
        gpt.click("#box")
        gpt.keyboard.type("this message is typed while capture is paused")
        gpt.keyboard.press("Enter")
        gpt.wait_for_timeout(1800)
        assert len(popup.evaluate(STORED)) == 5
        popup.check("#on")

        app = ctx.new_page()  # the web app is offered the captures and builds from them
        app.goto(f"{site}/app/")
        app.wait_for_selector("#ext.on", timeout=8000)
        app.click("#extAdd")
        app.wait_for_selector("#list li")
        app.click("#build")
        app.wait_for_selector("#result.on", timeout=60_000)
        numbers = app.evaluate("window.__brainprint.payload.numbers")
        assert numbers["items"] == 4 and {s["id"] for s in numbers["sources"]} == {"chatgpt", "claude", "gemini", "perplexity"}

        with popup.expect_download() as download:
            popup.click("#save")
        saved = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
        assert saved["format"] == "brainprint-capture" and len(saved["items"]) == 5
        popup.click("#clear")
        popup.click("#clear")
        popup.wait_for_timeout(300)
        assert popup.evaluate(STORED) == [] and popup.inner_text("#say") == "0 messages saved"
        ctx.close()
