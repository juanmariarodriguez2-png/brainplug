"""Exercise the release script as a CLI, without touching dist/ or source files."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "package_extension.py"
EXPECTED = {
    "manifest.json", "background.js", "bridge.js", "content.js", "popup.js",
    "popup.html", "popup.css", "icons/16.png", "icons/48.png", "icons/128.png",
}


def run_script(output, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(output), *map(str, args)],
        cwd=output.parent, capture_output=True, text=True,
    )


def test_package_extension(tmp_path):
    output = tmp_path / "release"
    result = run_script(output)
    assert result.returncode == 0, result.stderr
    version = json.loads((ROOT / "extension" / "manifest.json").read_text())["version"]
    target = output / f"brainplug-capture-{version}.zip"
    assert Path(result.stdout.strip()) == target
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == EXPECTED
        assert len(archive.namelist()) == len(EXPECTED)
        for name in EXPECTED:
            assert archive.read(name) == (ROOT / "extension" / name).read_bytes()


def test_package_omits_unreferenced_files(tmp_path):
    source = tmp_path / "extension"
    shutil.copytree(ROOT / "extension", source)
    for name in ("README.md", ".DS_Store", "secret.json", "unused.js", "icons/unused.png"):
        (source / name).write_text("not a runtime resource")
    result = run_script(tmp_path / "release", "--extension-dir", source)
    assert result.returncode == 0, result.stderr
    with ZipFile(next((tmp_path / "release").glob("*.zip"))) as archive:
        assert set(archive.namelist()) == EXPECTED


@pytest.mark.parametrize("missing", sorted(EXPECTED - {"manifest.json"}))
def test_package_rejects_missing_resources(tmp_path, missing):
    source = tmp_path / "extension"
    shutil.copytree(ROOT / "extension", source)
    (source / missing).unlink()
    output = tmp_path / "release"
    result = run_script(output, "--extension-dir", source)
    assert result.returncode != 0
    assert f"Missing extension resource: {missing}" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("reference", ["../outside.js", "/outside.js", "https://example.com/code.js"])
def test_package_rejects_nonlocal_resources(tmp_path, reference):
    source = tmp_path / "extension"
    shutil.copytree(ROOT / "extension", source)
    path = source / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["background"]["service_worker"] = reference
    path.write_text(json.dumps(manifest))
    result = run_script(tmp_path / "release", "--extension-dir", source)
    assert result.returncode != 0
    assert "Invalid extension resource" in result.stderr
    assert not (tmp_path / "release").exists()
