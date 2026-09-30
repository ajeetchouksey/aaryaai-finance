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

## Set it up

1. Install aaryaai finance (see [Getting started](getting-started.md)) and run the setup once.
2. Get the configuration snippet: open **Routines → Connections → Connect an MCP app** and copy it. Or run:

   ```bash
   aaryaai-finance mcp --config
   ```

   It prints something like:

   ```json
   {"mcpServers": {"aaryaai-finance": {"command": "/path/to/python", "args": ["-m", "aaryaai_finance", "mcp", "--data-dir", "/path/to/aaryaai-finance-data"]}}}
   ```

3. Add it to your assistant:
   - **Claude Desktop:** Settings → Developer → Edit config. Merge the snippet into `claude_desktop_config.json`, then restart Claude Desktop.
   - **VS Code:** put the `aaryaai-finance` entry under `servers` in `.vscode/mcp.json` (or your user `mcp.json`), then start it from the MCP view. Copilot Chat in agent mode can use its tools.
4. Ask something like *"Using aaryaai-finance, where will the money for my next flat payment come from?"*

## Try it by hand

```bash
aaryaai-finance mcp --data-dir PATH
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","clientInfo":{"name":"test"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

Each line you type is one JSON-RPC message; each reply comes back on one line.
