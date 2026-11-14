"""brainplug connect and brainplug doctor, against a pretend home folder (never your real settings)."""

import json
import os
import sys

import pytest

from brainplug import connect as bc
from brainplug.__main__ import main
from helpers import notes_folder


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    for name, value in (("HOME", h), ("USERPROFILE", h), ("APPDATA", h / "AppData" / "Roaming"),
                        ("XDG_CONFIG_HOME", h / ".config"), ("BRAINPLUG_CACHE", tmp_path / "cache")):
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return h


def fake_which(found):
    return lambda name, *a, **k: found.get(name)


def test_connect_adds_brainplug_to_every_assistant_found(home, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bc.shutil, "which", fake_which({"brainplug": "/opt/tools/brainplug"}))
    vault = tmp_path / "Vault"
    vault.mkdir()
    claude = bc._app_config("Claude")
    claude.mkdir(parents=True)
    (claude / "claude_desktop_config.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    (home / ".cursor").mkdir()
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('model = "o4"\n\n[mcp_servers.other]\ncommand = "y"\n')
    (home / ".gemini").mkdir()
    assert main(["connect", str(vault)]) == 0
    desktop = json.loads((claude / "claude_desktop_config.json").read_text())
    assert desktop["theme"] == "dark" and desktop["mcpServers"]["other"] == {"command": "x"}  # nothing else changes
    entry = desktop["mcpServers"]["brainplug"]
    assert entry == {"command": os.path.abspath("/opt/tools/brainplug"), "args": ["mcp", "--brain", str(vault.resolve())]}
    assert len(list(claude.glob("claude_desktop_config.json.*.bak"))) == 1  # a backup of what was there
    assert json.loads((home / ".cursor" / "mcp.json").read_text())["mcpServers"]["brainplug"] == entry
    assert json.loads((home / ".gemini" / "settings.json").read_text())["mcpServers"]["brainplug"] == entry
    toml = (home / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.brainplug]" in toml and 'model = "o4"' in toml and "[mcp_servers.other]" in toml
    if sys.version_info >= (3, 11):
        import tomllib
        assert tomllib.loads(toml)["mcp_servers"]["brainplug"] == entry
    out = capsys.readouterr().out
    assert "Restart the assistants" in out and "What do you know about me?" in out and "Windsurf" not in out
    assert (vault / "Brainplug" / "About me.md").exists()

    # once more: nothing changes and no new backup is made
    assert main(["connect", str(vault)]) == 0 and "unchanged" in capsys.readouterr().out
    assert len(list(claude.glob("*.bak"))) == 1
    # --print shows and changes nothing
    (home / ".codeium" / "windsurf").mkdir(parents=True)
    assert main(["connect", str(vault), "--print"]) == 0
    assert "would be added" in capsys.readouterr().out and not (home / ".codeium" / "windsurf" / "mcp_config.json").exists()


def test_connect_leaves_a_file_it_cannot_read(home, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bc.shutil, "which", fake_which({}))
    settings = bc._app_config("Code/User")
    settings.mkdir(parents=True)
    commented = '{\n  // my servers\n  "servers": {}\n}\n'
    (settings / "mcp.json").write_text(commented)
    (tmp_path / "Vault").mkdir()
    assert main(["connect", str(tmp_path / "Vault"), "--only", "vscode"]) == 0
    assert (settings / "mcp.json").read_text() == commented and "add this by hand" in capsys.readouterr().out
    assert bc.server_command(tmp_path / "Vault")[1][:2] == ["-m", "brainplug"]  # not installed as a command


def test_connect_finds_your_obsidian_vault(home, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bc.shutil, "which", fake_which({}))
    old, new = tmp_path / "Old vault", tmp_path / "Notes"
    old.mkdir()
    new.mkdir()
    config = bc._app_config("obsidian")
    config.mkdir(parents=True)
    (config / "obsidian.json").write_text(json.dumps({"vaults": {
        "a": {"path": str(old), "ts": 1700000000000}, "b": {"path": str(new), "ts": 1760000000000, "open": True},
        "c": {"path": str(tmp_path / "gone"), "ts": 1790000000000}}}))
    assert bc.obsidian_vaults() == [new, old]
    (home / ".cursor").mkdir()
    assert main(["connect"]) == 0
    assert f"Using your Obsidian vault {new} (the most recent of 2)" in capsys.readouterr().out
    assert str(new.resolve()) in json.loads((home / ".cursor" / "mcp.json").read_text())["mcpServers"]["brainplug"]["args"]


def test_doctor_checks_everything_end_to_end(home, tmp_path, monkeypatch, capsys):
    pytest.importorskip("mcp")
    monkeypatch.setattr(bc.shutil, "which", fake_which({}))  # the server starts as python -m brainplug
    vault = tmp_path / "Vault"
    notes_folder(vault, 20)
    (home / ".cursor").mkdir()
    assert main(["connect", str(vault)]) == 0
    (vault / "Brainplug" / "About me.md").write_text("# About me\n\n- Name: Ada\n- What I do: marine biology\n")
    capsys.readouterr()
    assert main(["doctor", str(vault)]) == 0
    out = capsys.readouterr().out
    assert "the server starts and answers" in out and "All good." in out and "✗" not in out
    (home / ".cursor" / "mcp.json").write_text('{"mcpServers": {"brainplug": {"command": "/no/such/brainplug", "args": []}}}')
    assert main(["doctor", str(vault)]) == 1
    assert "brainplug connect" in capsys.readouterr().out


def test_connect_refuses_a_vault_that_does_not_exist(home, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bc.shutil, "which", fake_which({}))
    (home / ".cursor").mkdir()
    assert main(["connect", str(tmp_path / "MyVualt")]) == 2 and "does not exist" in capsys.readouterr().out
    assert not (tmp_path / "MyVualt").exists() and not (home / ".cursor" / "mcp.json").exists()


def test_a_hanging_assistant_cli_is_reported_not_fatal(monkeypatch):
    def hang(*a, **k):
        raise bc.subprocess.TimeoutExpired("claude", 60)
    monkeypatch.setattr(bc.subprocess, "run", hang)
    assert bc._run(["claude", "mcp", "add"]).returncode == 1
