"""Read your Notion pages through the official Notion API.

Why: a Notion *export* does not include the day a page was created (unless the
page has a date property), so those pages come out as "no date". The API does
return ``created_time`` for every page.

Setup (once): create an internal integration at notion.so/my-integrations,
share the pages you want with it (page menu > Connections), and put its secret
in the ``NOTION_TOKEN`` environment variable. Then::

    python -m brainprint build --notion -o my_brain.html

Requests go from your computer straight to api.notion.com and nowhere else.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Callable

from .sources import MAX_NOTE_BYTES, Item, parse_date

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
MAX_BLOCKS = 600  # per page
MAX_DEPTH = 3


class NotionError(ValueError):
    pass


def _call(token: str, method: str, url: str, body: dict | None = None, retries: int = 4) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {token}", "Notion-Version": VERSION,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < retries:  # rate limit: wait as long as Notion asks
                time.sleep(min(30.0, float(err.headers.get("Retry-After") or 1)))
                continue
            if err.code == 401:
                raise NotionError("Notion rejected the token. Check NOTION_TOKEN.") from err
            if err.code in (403, 404):
                raise NotionError("Notion: that page is not shared with your integration.") from err
            raise NotionError(f"Notion API error {err.code}.") from err
        except urllib.error.URLError as err:
            raise NotionError(f"Could not reach Notion: {err.reason}") from err
    raise NotionError("Notion API: too many retries.")


def _plain(rich: list | None) -> str:
    return "".join(str(part.get("plain_text", "")) for part in rich or [] if isinstance(part, dict))


def _title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _plain(prop.get("title")).strip()
    return ""


def _tags(page: dict) -> list[str]:
    out = []
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "multi_select":
            out += [str(opt.get("name", "")) for opt in prop.get("multi_select") or []]
    return sorted({t for t in out if t})


def _blocks(token: str, base: str, block_id: str, depth: int, budget: list[int]) -> list[str]:
    lines, cursor = [], None
    while budget[0] > 0:
        url = f"{base}/blocks/{block_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        data = _call(token, "GET", url)
        for block in data.get("results") or []:
            budget[0] -= 1
            kind = block.get("type")
            if kind in ("child_page", "child_database"):
                continue  # those are pages of their own
            body = block.get(kind) if isinstance(block.get(kind), dict) else {}
            text = _plain(body.get("rich_text"))
            if text.strip() and kind != "code":
                lines.append(text)
            if block.get("has_children") and depth < MAX_DEPTH and budget[0] > 0:
                lines += _blocks(token, base, block["id"], depth + 1, budget)
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            break
    return lines


def load_notion(token: str, base: str = API, say: Callable[[str], None] | None = None,
                limit: int = 5000) -> list[Item]:
    """Every page shared with the integration, with its real creation date."""
    if not token:
        raise NotionError("Set the NOTION_TOKEN environment variable to your integration secret.")
    pages, cursor = [], None
    while len(pages) < limit:
        body = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = _call(token, "POST", f"{base}/search", body)
        pages += [p for p in data.get("results") or [] if not (p.get("archived") or p.get("in_trash"))]
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            break
    items = []
    for n, page in enumerate(pages[:limit], 1):
        if say and n % 25 == 0:
            say(f"Notion: {n}/{len(pages)} pages")
        created = parse_date(page.get("created_time"))
        if created is None:
            continue
        try:
            lines = _blocks(token, base, page["id"], 0, [MAX_BLOCKS])
        except NotionError:
            continue  # one unreadable page should not stop the rest
        text = re.sub(r"\s+", " ", re.sub(r"https?://\S+", " ", " ".join(lines))).strip()
        if len(text.split()) < 3:
            continue
        items.append(Item(
            id=f"notion:{page['id'].replace('-', '')}", title=_title(page) or "Untitled", created=created,
            source="notion", kind="note", text=text[:MAX_NOTE_BYTES], tags=_tags(page),
        ))
    return items
