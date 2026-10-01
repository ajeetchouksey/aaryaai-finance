# Use your numbers in Claude Desktop, VS Code and other MCP apps

aaryaai finance includes an MCP server, so an AI assistant on your computer can read your numbers and suggest changes. Examples:

- Claude Desktop
- VS Code with GitHub Copilot
- any other app that supports the Model Context Protocol

## How it works

- It runs **only when your assistant starts it**, as a local process talking over stdin/stdout. It opens no network port.
- It reads the same data folder as the app.
- **Read tools:** `get_snapshot`, `cash_forecast`, `list_deadlines`, `goal_odds`, `diversification`, `opportunities`, `tax_status`.
- **Suggest tools:** `propose_transaction` and `propose_planned_item`. They change nothing: the suggestion waits on the Routines screen until you approve it.
- Every call is written to the audit log (Routines → Audit log).

What your assistant sends onwards, and where, depends on that assistant and its AI provider.

## Set it up — automatic

The app can add itself to Claude Desktop and VS Code for you. It finds their settings file, adds one entry called `aaryaai-finance`, leaves every other entry as it was, and keeps a backup of the file (`…json.bak-<date>`).

**In the app:** open **Routines → Connections**. Each app found on this computer has a **Connect** button (and **Disconnect** later). During first-time setup, the last step offers the same as a checkbox.

**From the command line:**

```bash
aaryaai-finance mcp --setup all          # every app found: Claude Desktop, VS Code, VS Code Insiders
aaryaai-finance mcp --setup claude       # just one
aaryaai-finance mcp --status             # what's installed and connected
aaryaai-finance mcp --remove claude      # take it out again
```

With `start.bat` on Windows, run these with `.venv\Scripts\aaryaai-finance` inside the app folder.

Then:
- **Claude Desktop:** quit it completely (also from the system tray or menu bar) and open it again. aaryaai-finance appears under the tools button in the chat box.
- **VS Code:** open the MCP servers list (Command Palette → *MCP: List Servers*), start aaryaai-finance, and use Copilot Chat in **Agent** mode. Your organisation's Copilot policy must allow MCP.

Where the settings live:

| App | Windows | macOS | Linux |
|---|---|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` (and the Microsoft Store copy under `%LOCALAPPDATA%\Packages\Claude_*`) | `~/Library/Application Support/Claude/` | `~/.config/Claude/` |
| VS Code | `%APPDATA%\Code\User\mcp.json` | `~/Library/Application Support/Code/User/mcp.json` | `~/.config/Code/User/mcp.json` |

The app must be installed and opened once, so that its settings folder exists. If a settings file can't be read (broken JSON), it is left untouched and the reason is shown. VS Code files with comments are accepted; the comments are removed when the entry is added, and the backup keeps the original.

## Set it up — by hand

1. Get the configuration snippet: **Routines → Connections → Set it up by hand instead**, or run `aaryaai-finance mcp --config`. It prints something like:

   ```json
   {"mcpServers": {"aaryaai-finance": {"command": "/path/to/python", "args": ["-m", "aaryaai_finance", "mcp", "--data-dir", "/path/to/aaryaai-finance-data"]}}}
   ```

2. Add it to your assistant:
   - **Claude Desktop:** Settings → Developer → Edit config. Merge the snippet into `claude_desktop_config.json` and restart Claude Desktop.
   - **VS Code:** put the `aaryaai-finance` entry under `servers` in your user `mcp.json` (Command Palette → *MCP: Open User Configuration*) with `"type": "stdio"`, then start it from the MCP view.
3. Ask something like *"Using aaryaai-finance, where will the money for my next flat payment come from?"*

## Microsoft 365 Copilot and the Windows Copilot app

Microsoft 365 Copilot only uses remote MCP servers that an organisation's admins add through Copilot Studio; it can't start a program on your computer, and personal finances don't belong in a work tenant. The Copilot app in Windows doesn't offer a way to add your own MCP server as of mid-2026. Use Claude Desktop, or VS Code with GitHub Copilot.

## Try it by hand

```bash
aaryaai-finance mcp --data-dir PATH
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","clientInfo":{"name":"test"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

Each line you type is one JSON-RPC message; each reply comes back on one line.
