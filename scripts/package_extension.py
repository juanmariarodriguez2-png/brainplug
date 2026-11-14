"""Build the Chrome Web Store ZIP, without dependencies.

    python scripts/package_extension.py [--output-dir dist]

Only manifest entry points and their local HTML/CSS resources are packaged.
The extension's JavaScript is self-contained (no imports or remote code).
"""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
ASSETS = {".js", ".html", ".css", ".png", ".svg", ".ico", ".jpg", ".jpeg", ".webp", ".gif"}


class HTMLResources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        key = {"script": "src", "link": "href", "img": "src"}.get(tag)
        if key and attrs.get(key):
            self.paths.append(attrs[key])


def manifest_resources(manifest: dict) -> list[str]:
    """File references used by the capture extension's manifest."""
    paths = list(manifest.get("icons", {}).values())
    action = manifest.get("action", {})
    if action.get("default_popup"):
        paths.append(action["default_popup"])
    icons = action.get("default_icon", {})
    paths.extend([icons] if isinstance(icons, str) else icons.values())
    background = manifest.get("background", {})
    if background.get("service_worker"):
        paths.append(background["service_worker"])
    for script in manifest.get("content_scripts", []):
        paths.extend(script.get("js", []))
        paths.extend(script.get("css", []))
    return paths


def package(extension_dir: Path, output_dir: Path) -> Path:
    extension_dir = extension_dir.resolve()
    manifest_path = extension_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest["version"]
    if not isinstance(version, str) or not re.fullmatch(r"\d+(?:\.\d+){0,3}", version):
        raise ValueError("Invalid manifest version")

    files = {"manifest.json": manifest_path}
    pending = [(PurePosixPath(), ref) for ref in manifest_resources(manifest)]
    while pending:
        parent, ref = pending.pop()
        # References must be packaged local files, never remote URLs or escapes.
        relative = parent / ref
        if not ref or ":" in ref or "\\" in ref or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Invalid extension resource: {ref}")
        name = relative.as_posix()
        path = extension_dir / name
        if not path.resolve().is_relative_to(extension_dir):
            raise ValueError(f"Resource outside extension: {name}")
        if not path.is_file():
            raise ValueError(f"Missing extension resource: {name}")
        if path.suffix.lower() not in ASSETS:
            raise ValueError(f"Unsupported extension resource: {name}")
        if name in files:
            continue
        files[name] = path
        refs = []
        if path.suffix == ".html":
            parser = HTMLResources()
            parser.feed(path.read_text(encoding="utf-8"))
            refs = parser.paths
        elif path.suffix == ".css":
            refs = re.findall(r"url\(\s*['\"]?([^'\"\s)]+)['\"]?\s*\)", path.read_text(encoding="utf-8"))
        pending.extend((relative.parent, ref) for ref in refs)

    # Validate the complete resource set before creating an archive.
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"brainplug-capture-{version}.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--extension-dir", type=Path, default=ROOT / "extension")
    args = parser.parse_args()
    try:
        target = package(args.extension_dir, args.output_dir)
    except (OSError, ValueError, KeyError) as err:
        parser.exit(1, f"Packaging failed: {err}\n")
    print(target)


if __name__ == "__main__":
    main()
