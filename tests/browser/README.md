# Browser checks

These drive the real pages in Chrome, so they are not part of the normal test run
(`python -m pytest` skips them unless Playwright and Chrome are available).

```bash
pip install playwright pytest
export BRAINPRINT_CHROME=/path/to/chrome      # Chrome for Testing or Chromium
python -m pytest tests/browser -q
```

* `test_web_app.py` opens `docs/app/`, adds one file of every supported format, builds the
  brain in the page and checks that the numbers match the Python package, that the result
  renders and that the page talks to no other server.
* `test_extension.py` loads `extension/` into Chrome, types into stand-in pages served on
  the real addresses of ChatGPT, Claude, Gemini and Perplexity, and checks what is stored:
  only what you sent, nothing while paused, the same conversation id as the address bar.
  It then hands the captures to the web app. The live sites themselves are not contacted.
