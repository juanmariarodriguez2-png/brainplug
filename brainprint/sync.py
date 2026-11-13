"""Keep your brainprint up to date.

``brainprint sync --init …`` saves which files and folders make up your record
in ``brainprint.json``. After that, ``brainprint sync`` rebuilds it in one
step, and ``brainprint sync --watch`` rebuilds whenever something changes: a
new note in your vault, a fresh export, a new capture file from the browser
extension.

To use it on several devices, keep the output (or the ``--vault`` notes) in a
folder that already syncs: iCloud, Google Drive, Dropbox, Obsidian Sync.
Brainprint has no servers of its own.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, fields
from pathlib import Path
from typing import Callable

from .pipeline import Options, run

CONFIG = "brainprint.json"
_PATHS = ("out", "vault", "json", "dataset")
MAX_FILES = 200_000


def write_config(o: Options, path: str | Path = CONFIG) -> Path:
    path = Path(path)
    data = asdict(o)
    data["inputs"] = [str(Path(p).expanduser().resolve()) for p in o.inputs]
    data["rename"] = {str(k + 1): v for k, v in o.rename.items()}  # people count topics from 1
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_config(path: str | Path = CONFIG) -> Options:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No {path.name} here. Create it with: brainprint sync --init <your files and folders>")
    data = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Options)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"{path.name}: unknown setting(s): {', '.join(unknown)}")
    base = path.resolve().parent

    def rel(p):  # paths in the file are relative to the file
        p = Path(str(p)).expanduser()
        return str(p if p.is_absolute() else base / p)

    data["inputs"] = [rel(p) for p in data.get("inputs") or []]
    for key in _PATHS:
        if data.get(key):
            data[key] = rel(data[key])
    data["rename"] = {int(k) - 1: v for k, v in (data.get("rename") or {}).items()}
    return Options(**data)


def fingerprint(inputs: list[str]) -> str:
    """Changes whenever a file under the inputs is added, removed or modified."""
    h = hashlib.sha1()
    count = 0
    for raw in inputs:
        root = Path(raw)
        if not root.exists():
            h.update(f"missing:{raw}".encode())
            continue
        files = [root] if root.is_file() else sorted(
            p for p in root.rglob("*")
            if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts))
        for p in files:
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
            count += 1
            if count >= MAX_FILES:
                break
    return h.hexdigest()


def watch(config: str | Path = CONFIG, every: float = 30.0, say: Callable[[str], None] = print,
          cycles: int | None = None, build: Callable[[Options], object] | None = None) -> int:
    """Rebuild now, then again each time the inputs change. Returns the number of builds."""
    build = build or (lambda o: run(o, say))
    builds, seen, pending = 0, None, None
    n = 0
    while cycles is None or n < cycles:
        n += 1
        try:
            o = read_config(config)
            now = fingerprint(o.inputs)
            # wait until the files stop changing (a sync client may still be writing)
            if now != seen and (seen is None or now == pending):
                say(f"[{time.strftime('%H:%M:%S')}] " + ("building…" if seen is None else "change detected, rebuilding…"))
                build(o)
                builds, seen, pending = builds + 1, now, None
            else:
                pending = now if now != seen else None
        except (ValueError, FileNotFoundError) as err:
            say(f"[{time.strftime('%H:%M:%S')}] {err}")
        if cycles is None or n < cycles:
            time.sleep(every)
    return builds
