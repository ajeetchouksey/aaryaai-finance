"""Command line.

  aaryaai-finance                 start the app and open your browser
  aaryaai-finance mcp             run the MCP server for an AI assistant on this computer (stdio)
  aaryaai-finance mcp --config    print the snippet to paste into Claude Desktop / VS Code
  aaryaai-finance mcp --setup all connect every MCP app found on this computer (Claude Desktop, VS Code)
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["mcp"]:
        sys.exit(mcp(argv[1:]) or 0)
    ap = argparse.ArgumentParser(prog="aaryaai-finance", description="Local-first personal finance manager (aaryaai).",
                                 epilog="Also: 'aaryaai-finance mcp' runs the MCP server for AI assistants on this computer.")
    ap.add_argument("--data-dir", type=Path, help="Folder that holds your data (default: the one you chose in setup)")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")
    ap.add_argument("--no-routines", action="store_true", help="Don't run scheduled routines in the background")
    ap.add_argument("--version", action="version", version=f"aaryaai-finance {__version__}")
    a = ap.parse_args(argv)

    import uvicorn
    from .server import create_app
    app = create_app(a.data_dir)
    if not a.no_routines:
        from .core.routines import start_background
        start_background(app.state.get_ctx)
    url = f"http://127.0.0.1:{a.port}"
    print(f"\n  aaryaai-finance {__version__} running at {url}  (Ctrl+C to stop)\n")
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


def mcp(argv):
    ap = argparse.ArgumentParser(prog="aaryaai-finance mcp", description="MCP server over stdio for AI assistants on this computer.")
    ap.add_argument("--data-dir", type=Path, help="Your data folder (default: the one you chose in setup)")
    ap.add_argument("--config", action="store_true", help="Print the configuration snippet for Claude Desktop / VS Code and exit")
    ap.add_argument("--setup", metavar="APP", action="append", choices=["claude", "vscode", "vscode-insiders", "all"],
                    help="Add aaryaai-finance to that app's MCP settings (claude, vscode, vscode-insiders or all). A backup is kept.")
    ap.add_argument("--remove", metavar="APP", action="append", choices=["claude", "vscode", "vscode-insiders"],
                    help="Remove aaryaai-finance from that app's MCP settings")
    ap.add_argument("--status", action="store_true", help="Show which apps are installed and connected")
    a = ap.parse_args(argv)
    from .config import default_data_dir, remembered_data_dir
    data_dir = a.data_dir or remembered_data_dir() or default_data_dir()
    if a.setup or a.remove or a.status:
        from . import mcp_setup as ms
        code = 0
        enc = (getattr(sys.stdout, "encoding", None) or "utf-8").lower()
        if "utf" not in enc:                       # e.g. an old Windows console: keep the output plain
            for c in ms.CLIENTS.values():
                c["label"] = c["label"].replace(" · ", " - ")
        for c in a.remove or []:
            r = ms.uninstall(c)
            print(f"{r['label']}: " + ("removed from " + ", ".join(x["path"] for x in r["removed"]) if r["removed"] else "nothing to remove"))
        targets = a.setup or []
        if "all" in targets:
            targets = [x["id"] for x in ms.status(data_dir) if x["installed"]]
            if not targets:
                print("Neither Claude Desktop nor VS Code was found on this computer.")
        for c in targets:
            try:
                r = ms.install(c, data_dir)
                for w in r["written"]:
                    print(f"{r['label']}: connected in {w['path']}" + (f" (backup: {w['backup']})" if w["backup"] else ""))
                print(f"  Next: {r['next']}")
            except ValueError as e:
                print(f"{ms.CLIENTS[c]['label']}: {e}"); code = 1
        if a.status:
            for x in ms.status(data_dir):
                print(f"{x['label'].replace(' · ', ' - ') if 'utf' not in enc else x['label']:<36} {x['state'].replace('_', ' ')}" + (f"  ({', '.join(x['paths'])})" if x["paths"] else ""))
        return code
    from .mcp_server import Server, config_snippet
    if a.config:
        print(json.dumps(config_snippet(data_dir), indent=2))
        return
    Server(a.data_dir).serve()


if __name__ == "__main__":
    main()
