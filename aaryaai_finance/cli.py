"""Command line: `aaryaai-finance` starts the app and opens your browser."""
from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from . import __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aaryaai-finance", description="Local-first personal finance manager (aaryaai).")
    ap.add_argument("--data-dir", type=Path, help="Folder that holds your data (default: the one you chose in setup)")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")
    ap.add_argument("--version", action="version", version=f"aaryaai-finance {__version__}")
    a = ap.parse_args(argv)

    import uvicorn
    from .server import create_app
    app = create_app(a.data_dir)
    url = f"http://127.0.0.1:{a.port}"
    print(f"\n  aaryaai-finance {__version__} running at {url}  (Ctrl+C to stop)\n")
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
