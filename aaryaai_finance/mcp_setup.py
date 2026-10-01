"""Connect the MCP server to Claude Desktop or VS Code (GitHub Copilot) for the user.

- Finds each app's MCP configuration file on this computer.
- Adds (or updates) one entry named "aaryaai-finance" and leaves every other entry exactly as it was.
- Backs up the file first (<name>.bak-YYYYmmdd-HHMMSS) and writes atomically.
- If the existing file isn't valid JSON (VS Code allows comments), comments and trailing commas are
  removed before merging; the backup keeps the original. A file that still can't be read is never touched.

Nothing here runs unless you ask: Routines → Connections → Connect, the setup wizard's checkbox,
or `aaryaai-finance mcp --setup claude|vscode`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

NAME = "aaryaai-finance"

CLIENTS = {
    "claude": {"label": "Claude Desktop", "key": "mcpServers", "restart": "Quit Claude Desktop completely (also from the system tray / menu bar) and open it again."},
    "vscode": {"label": "VS Code · GitHub Copilot", "key": "servers", "restart": "In VS Code, open the MCP servers list and start aaryaai-finance, then use Copilot Chat in Agent mode."},
    "vscode-insiders": {"label": "VS Code Insiders · GitHub Copilot", "key": "servers", "restart": "In VS Code Insiders, start aaryaai-finance from the MCP servers list, then use Copilot Chat in Agent mode."},
}


def _home() -> Path:
    return Path(os.environ.get("AARYAAI_FAKE_HOME") or Path.home())


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or _home() / "AppData" / "Roaming")


def config_paths(client: str, platform: str | None = None) -> list[Path]:
    """Where the app reads its MCP configuration. Only folders that exist count as 'installed'."""
    platform = platform or sys.platform
    home = _home()
    if client == "claude":
        if platform.startswith("win"):
            out = [_appdata() / "Claude"]
            local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
            out += sorted(local.glob("Packages/Claude_*/LocalCache/Roaming/Claude"))     # Microsoft Store version
        elif platform == "darwin":
            out = [home / "Library" / "Application Support" / "Claude"]
        else:
            out = [Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "Claude"]
        return [d / "claude_desktop_config.json" for d in out]
    folder = {"vscode": "Code", "vscode-insiders": "Code - Insiders"}[client]
    if platform.startswith("win"):
        base = _appdata()
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return [base / folder / "User" / "mcp.json"]


def entry(client: str, data_dir: Path, python: str | None = None) -> dict:
    e = {"command": python or sys.executable, "args": ["-m", "aaryaai_finance", "mcp", "--data-dir", str(Path(data_dir).resolve())]}
    return {"type": "stdio", **e} if client.startswith("vscode") else e


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas, leaving strings alone."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if ch == '"':
                in_str = False
            i += 1
        elif ch == '"':
            in_str = True; out.append(ch); i += 1
        elif text.startswith("//", i):
            while i < n and text[i] not in "\r\n":
                i += 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(ch); i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _read(p: Path) -> tuple[dict, bool]:
    """(config, had_comments). Raises ValueError if it can't be read safely."""
    if not p.exists():
        return {}, False
    text = p.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}, False
    try:
        d = json.loads(text)
        cleaned = False
    except ValueError:
        try:
            d = json.loads(_strip_jsonc(text))
            cleaned = True
        except ValueError as e:
            raise ValueError(f"{p} isn't valid JSON ({e}). Fix it or connect by hand; it was not changed.") from None
    if not isinstance(d, dict):
        raise ValueError(f"{p} doesn't contain a JSON object; it was not changed.")
    return d, cleaned


def status(data_dir: Path, python: str | None = None, platform: str | None = None) -> list[dict]:
    out = []
    for cid, c in CLIENTS.items():
        found = [p for p in config_paths(cid, platform) if p.parent.exists()]
        want = entry(cid, data_dir, python)
        states, problem = [], None
        for p in found:
            try:
                d, _ = _read(p)
            except ValueError as e:
                states.append("unreadable"); problem = str(e)
                continue
            cur = (d.get(c["key"]) or {}).get(NAME) if isinstance(d.get(c["key"]), dict) else None
            states.append("not_connected" if cur is None else
                          "connected" if (cur.get("command") == want["command"] and cur.get("args") == want["args"]) else "outdated")
        if not found:
            state = "not_found"
        elif "unreadable" in states:
            state = "unreadable"
        elif all(x == "connected" for x in states):
            state = "connected"
        elif any(x in ("connected", "outdated") for x in states):
            state = "outdated"
        else:
            state = "not_connected"
        out.append({"id": cid, "label": c["label"], "installed": bool(found), "state": state, "paths": [str(p) for p in found],
                    "problem": problem, "restart": c["restart"]})
    return out


def _write(p: Path, d: dict) -> Path | None:
    p.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if p.exists():
        stamp, n = f"{datetime.now():%Y%m%d-%H%M%S}", 0
        backup = p.with_name(f"{p.name}.bak-{stamp}")
        while backup.exists():                       # never overwrite an earlier backup, even within the same second
            n += 1
            backup = p.with_name(f"{p.name}.bak-{stamp}-{n}")
        backup.write_bytes(p.read_bytes())
    tmp = p.with_name(p.name + ".tmp-aaryaai")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return backup


def install(client: str, data_dir: Path, python: str | None = None, platform: str | None = None) -> dict:
    if client not in CLIENTS:
        raise ValueError(f"Unknown app '{client}'. Choose: {', '.join(CLIENTS)}")
    c = CLIENTS[client]
    paths = [p for p in config_paths(client, platform) if p.parent.exists()]
    if not paths:
        raise ValueError(f"{c['label']} doesn't seem to be installed on this computer (no settings folder yet). Install it and open it once, then try again.")
    reads = [(p, *_read(p)) for p in paths]          # read all first: change nothing if any file is unreadable
    written = []
    for p, d, cleaned in reads:
        d.setdefault(c["key"], {})
        if not isinstance(d[c["key"]], dict):
            raise ValueError(f"'{c['key']}' in {p} isn't an object; it was not changed.")
        d[c["key"]][NAME] = entry(client, data_dir, python)
        backup = _write(p, d)
        written.append({"path": str(p), "backup": str(backup) if backup else None, "comments_removed": cleaned})
    return {"client": client, "label": c["label"], "written": written, "next": c["restart"]}


def uninstall(client: str, platform: str | None = None) -> dict:
    c = CLIENTS[client]
    removed = []
    for p in config_paths(client, platform):
        if not p.exists():
            continue
        d, _ = _read(p)
        if NAME in (d.get(c["key"]) or {}):
            del d[c["key"]][NAME]
            backup = _write(p, d)
            removed.append({"path": str(p), "backup": str(backup) if backup else None})
    return {"client": client, "label": c["label"], "removed": removed}
