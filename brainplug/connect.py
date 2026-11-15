"""Connect your AI assistants to your brain, and check that it works.

    brainplug connect ~/Vault                    # every assistant found on this computer
    brainplug connect ~/Vault --only cursor,codex
    brainplug connect --print                    # show what would change, change nothing
    brainplug doctor ~/Vault                     # check everything, end to end

Each assistant's own settings file gets one "brainplug" entry (other entries are
kept, and the file is backed up first). The command written there is an absolute
path, because desktop apps do not see the PATH your terminal sees.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__, memory

NAME = "brainplug"
FIRST_QUESTIONS = (
    '"What do you know about me?"',
    '"When did I first write about <a topic>?"',
    '"What was I working on last spring?"',
    '"Remember that I prefer short answers."',
)


def _home() -> Path:
    return Path.home()


def _app_config(folder: str) -> Path:
    """Where desktop apps keep their settings on this system."""
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / folder
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or _home() / "AppData" / "Roaming") / folder
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config") / folder


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or _home() / ".codex").expanduser()


@dataclass
class Client:
    key: str
    name: str
    config: Path | None = None  # a JSON settings file with a map of servers
    servers: str = "mcpServers"  # the name of that map
    cli: str = ""  # a command line tool that registers servers itself
    marker: Path | None = None  # its presence means the assistant is installed

    def found(self) -> bool:
        return bool((self.cli and shutil.which(self.cli)) or (self.marker and self.marker.exists()))


def _claude_desktop() -> list[Client]:
    """Claude Desktop reads %APPDATA%\\Claude (or the macOS/Linux equivalent). Installed as a Windows
    app package (MSIX), it reads a virtualized copy instead, under
    %LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude, and its own "Edit Config"
    button may open the copy it does not read. Both get the entry when both exist."""
    found = [Client("claude-desktop", "Claude Desktop", _app_config("Claude") / "claude_desktop_config.json",
                    marker=_app_config("Claude"))]
    local = os.environ.get("LOCALAPPDATA")
    for package in sorted(Path(local).glob("Packages/Claude_*")) if local else []:
        folder = package / "LocalCache" / "Roaming" / "Claude"
        found.append(Client("claude-desktop", "Claude Desktop", folder / "claude_desktop_config.json", marker=package))
    return found


def clients() -> list[Client]:
    home = _home()
    return [
        *_claude_desktop(),
        Client("claude-code", "Claude Code", cli="claude", marker=home / ".claude"),
        Client("cursor", "Cursor", home / ".cursor" / "mcp.json", marker=home / ".cursor"),
        Client("codex", "Codex", _codex_home() / "config.toml", cli="codex", marker=_codex_home()),
        Client("windsurf", "Windsurf", home / ".codeium" / "windsurf" / "mcp_config.json",
               marker=home / ".codeium" / "windsurf"),
        Client("gemini", "Gemini CLI", home / ".gemini" / "settings.json", marker=home / ".gemini"),
        Client("vscode", "VS Code", _app_config("Code/User") / "mcp.json", servers="servers",
               marker=_app_config("Code/User")),
        Client("lmstudio", "LM Studio", home / ".lmstudio" / "mcp.json", marker=home / ".lmstudio"),
    ]


def server_command(vault: str | Path | None, inputs: list[str] | None = None,
                   sessions: bool = False) -> tuple[str, list[str]]:
    """The absolute command that starts this Brainplug's MCP server."""
    args = ["mcp"] + (["--brain", str(Path(vault).expanduser().resolve())] if vault else [])
    args += [str(Path(p).expanduser().resolve()) for p in inputs or []] + (["--sessions"] if sessions else [])
    exe = shutil.which(NAME)
    temporary = exe and re.search(r"[\\/](?:uv[\\/]archive-|\.cache[\\/]uv[\\/]|pipx[\\/]\.cache)", exe)
    if exe and not temporary:
        return os.path.abspath(exe), args
    uvx = shutil.which("uvx")
    if temporary and uvx:  # started with uvx: let uvx find it again next time
        return os.path.abspath(uvx), [NAME, *args]
    return sys.executable, ["-m", NAME, *args]


def obsidian_vaults() -> list[Path]:
    """The vaults Obsidian knows about on this computer, most recently opened first."""
    places = [_app_config("obsidian") / "obsidian.json",
              _home() / ".var" / "app" / "md.obsidian.Obsidian" / "config" / "obsidian" / "obsidian.json"]
    found: list[tuple[float, Path]] = []
    for place in places:
        try:
            vaults = json.loads(place.read_text(encoding="utf-8")).get("vaults") or {}
        except (OSError, ValueError, AttributeError):
            continue
        for v in vaults.values():
            if isinstance(v, dict) and v.get("path") and Path(v["path"]).is_dir():
                found.append((float(v.get("ts") or 0), Path(v["path"])))
    return [p for _, p in sorted(found, key=lambda tp: -tp[0])]


# ------------------------------------------------------------------ writing
def _merge_json(path: Path, servers: str, entry: dict, dry: bool) -> str:
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except ValueError:
            return "unreadable"
        if not isinstance(data, dict) or not isinstance(data.get(servers, {}), dict):
            return "unreadable"
    table = data.setdefault(servers, {})
    if table.get(NAME) == entry:
        return "unchanged"
    state = "updated" if NAME in table else "added"
    if dry:
        return f"would be {state}"
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}.bak"))
    table[NAME] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return state


def _merge_toml(path: Path, command: str, args: list[str], dry: bool) -> str:
    block = f"[mcp_servers.{NAME}]\ncommand = {json.dumps(command)}\nargs = {json.dumps(args)}\n"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    section = re.compile(rf"(?ms)^\[mcp_servers\.{NAME}\]\n.*?(?=^\[|\Z)")
    old = section.search(text)
    if old and old.group(0).strip() == block.strip():
        return "unchanged"
    new = section.sub(block + "\n", text) if old else (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    if dry:
        return "would be " + ("updated" if old else "added")
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}.bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return "updated" if old else "added"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as err:  # a CLI that hangs or vanished: report it, go on
        return subprocess.CompletedProcess(cmd, 1, "", f"{type(err).__name__}: {err}")


def connect_one(client: Client, command: str, args: list[str], dry: bool = False) -> str:
    """Add Brainplug to one assistant. Returns what happened, in a few words."""
    if client.key in ("claude-code", "codex") and client.cli and shutil.which(client.cli):
        add = [client.cli, "mcp", "add"] + (["--scope", "user"] if client.key == "claude-code" else [])
        add += [NAME, "--", command, *args]
        if dry:
            return "would run: " + " ".join(add)
        _run([client.cli, "mcp", "remove", NAME] + (["--scope", "user"] if client.key == "claude-code" else []))
        done = _run(add)
        return "added" if done.returncode == 0 else f"failed: {(done.stderr or done.stdout).strip()[:200]}"
    if client.key == "codex" and client.config:
        return _merge_toml(client.config, command, args, dry)
    if client.config:
        entry = {"command": command, "args": args}
        if client.servers == "servers":
            entry = {"type": "stdio", **entry}
        return _merge_json(client.config, client.servers, entry, dry)
    return "manual"


def connect(vault: str | Path | None, inputs: list[str] | None = None, only: list[str] | None = None,
            sessions: bool = False, dry: bool = False, say=print) -> int:
    if vault is None:
        known = obsidian_vaults()
        if not known:
            say("Name the folder for your brain, e.g.: brainplug connect ~/Documents/MyVault")
            return 2
        vault = known[0]
        say(f"Using your Obsidian vault {vault}" + (f" (the most recent of {len(known)})" if len(known) > 1 else ""))
    if not Path(vault).expanduser().is_dir():
        say(f"{vault} does not exist. Check the path, or create it first with: brainplug brain \"{vault}\"")
        return 2
    if not dry:
        memory.init(vault)
    command, args = server_command(vault, inputs, sessions)
    say(f"Brainplug {__version__} will start as:\n  {command} {' '.join(args)}\n")
    wanted = [c for c in clients() if not only or c.key in only]
    unknown = sorted(set(only or []) - {c.key for c in clients()})
    if unknown:
        say(f"Unknown assistant(s): {', '.join(unknown)}. Known: {', '.join(c.key for c in clients())}.")
    connected = 0
    for client in wanted:
        if not client.found() and not only:
            continue
        state = connect_one(client, command, args, dry)
        connected += state in ("added", "updated", "unchanged")
        where = f" ({client.config})" if client.config and client.key not in ("claude-code",) else ""
        if state == "unreadable":
            state = "its settings file could not be read, so it was left as it is; add this by hand:\n    " + json.dumps(
                {client.servers: {NAME: {"command": command, "args": args}}})
        elif state == "manual":
            state = f"run: claude mcp add --scope user {NAME} -- {command} {' '.join(args)}"
        say(f"  {client.name:<15} {state}{where if state in ('added', 'updated', 'unchanged') else ''}")
    if not any(c.found() for c in wanted) and not only:
        say("  No assistant found on this computer. Install Claude Desktop, Claude Code, Cursor or Codex, "
            "or pass --only to write a settings file anyway.")
    if connected and not dry:
        say("\nRestart the assistants that were open. Then ask, for example:")
        say("  " + "\n  ".join(FIRST_QUESTIONS))
        say(f"\nCheck it any time with: brainplug doctor \"{vault}\"")
    return 0


# ------------------------------------------------------------------- doctor
def _handshake(command: str, args: list[str], timeout: float = 90.0) -> tuple[bool, str]:
    """Start the server exactly as an assistant would and ask it for the briefing."""
    try:
        import anyio  # noqa: F401  (comes with the MCP SDK)
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return False, "the MCP SDK is missing: reinstall Brainplug (uv tool install --force brainplug)"
    import asyncio

    import tempfile

    log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")  # what the server says, to show if it fails

    async def talk():
        began = time.monotonic()
        params = StdioServerParameters(command=command, args=args, env=dict(os.environ))
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = [t.name for t in (await session.list_tools()).tools]
                await session.call_tool("context", {})  # answers at once, before the files are read
                answered = time.monotonic() - began
                summary = (await session.call_tool("overview", {})).content[0].text  # waits for the index
                return answered, tools, summary

    try:
        took, tools, summary = asyncio.run(asyncio.wait_for(talk(), timeout))
    except Exception as err:  # noqa: BLE001  (shown to the person, who can act on it)
        log.seek(0)
        said = " | ".join(line.strip() for line in log.read().splitlines()[-3:] if line.strip())
        return False, f"the server did not answer: {type(err).__name__}: {err}" + (f" (it said: {said})" if said else "")
    finally:
        log.close()
    first = next((line for line in summary.splitlines() if line.strip()), "(empty)")
    return True, f"answered in {took:.1f} s with {len(tools)} tools; your brain: {first}"


def _registered(client: Client) -> tuple[str, list[str]] | None:
    """The command an assistant has for Brainplug, if any (from its settings file)."""
    path = client.config
    if not path or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix == ".toml":
        m = re.search(rf"(?ms)^\[mcp_servers\.{NAME}\]\n(.*?)(?=^\[|\Z)", text)
        if not m:
            return None
        command = re.search(r'^command\s*=\s*(".*")\s*$', m.group(1), re.M)
        args = re.search(r"^args\s*=\s*(\[.*\])\s*$", m.group(1), re.M)
        try:
            return json.loads(command.group(1)) if command else "", json.loads(args.group(1)) if args else []
        except ValueError:
            return "", []
    try:
        entry = (json.loads(text or "{}").get(client.servers) or {}).get(NAME)
    except (ValueError, AttributeError):
        return None
    return (entry.get("command", ""), entry.get("args", [])) if isinstance(entry, dict) else None


def doctor(vault: str | Path | None = None, say=print) -> int:
    problems = 0

    def check(good: bool, text: str, fix: str = "") -> None:
        nonlocal problems
        problems += not good
        say(f"  {'✓' if good else '✗'} {text}" + (f"\n      → {fix}" if fix and not good else ""))

    say(f"Brainplug {__version__} · Python {sys.version.split()[0]} · {sys.platform}")
    check(sys.version_info >= (3, 10), "Python 3.10 or later")
    try:
        import importlib.metadata as md
        check(True, f"MCP SDK {md.version('mcp')}")
    except Exception:  # noqa: BLE001
        check(False, "MCP SDK installed", "reinstall Brainplug: uv tool install --force brainplug")
    if vault is None:
        known = obsidian_vaults()
        vault = known[0] if known else None
    if vault is None:
        check(False, "a vault to check", "brainplug doctor ~/path/to/your/vault")
        return 1
    vault = Path(vault).expanduser()
    check(vault.is_dir(), f"vault {vault}", "create the folder, or point to your Obsidian vault")
    if vault.is_dir():
        base = memory.brain_dir(vault)
        check(base.is_dir(), "Brainplug folder in the vault", f'brainplug brain "{vault}"')
        about = memory.profile(vault)
        check(bool(about), '"About me" note filled in', f"write a few lines in {base / memory.PROFILE}")
        try:
            probe = base / memory.MEMORY / ".brainplug-write-check"
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            check(True, "memories can be saved")
        except OSError as err:
            check(False, "memories can be saved", f"the Memory folder is not writable: {err}")
        waiting = memory.pending(vault)
        if waiting:
            say(f"  ! {len(waiting)} preference(s) from assistants wait for your approval: "
                f'brainplug brain "{vault}" --review')
    command, args = server_command(vault)
    ok, said = _handshake(command, args)
    check(ok, f"the server starts and answers: {said}" if ok else "the server starts and answers", said)
    say("Assistants:")
    any_found = False
    for client in clients():
        if not client.found():
            continue
        any_found = True
        if client.key == "claude-code" and shutil.which("claude"):
            listed = _run(["claude", "mcp", "get", NAME])
            check(listed.returncode == 0, "Claude Code has Brainplug", f'brainplug connect "{vault}" --only claude-code')
            continue
        got = _registered(client)
        if got is None:
            check(False, f"{client.name} has Brainplug", f'brainplug connect "{vault}" --only {client.key}')
            continue
        cmd, cmd_args = got
        exists = bool(cmd) and (Path(cmd).exists() or bool(shutil.which(cmd)))
        same_vault = str(vault.resolve()) in [str(Path(a).expanduser()) for a in cmd_args] if cmd_args else False
        check(exists, f"{client.name}: the command exists ({cmd or 'none'})", f'brainplug connect "{vault}" --only {client.key}')
        if exists and not same_vault:
            say(f"  ! {client.name} uses another vault: {' '.join(cmd_args)}")
    if not any_found:
        say("  (no assistant found on this computer)")
    say("All good." if not problems else f"{problems} thing(s) to fix, listed above.")
    return 0 if not problems else 1
