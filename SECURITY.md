# Security

## Reporting a problem

Please report security problems privately through GitHub: **Security → Report a vulnerability** on the repository page. Don't open a public issue for them. You'll get an answer within a week.

Helpful details: the version (`aaryaai-finance --version`), your operating system, and the steps that show the problem. Use invented data, never your real finances.

## Supported versions

Only the latest release gets fixes. The app shows a notice when a newer version is out.

## How the app protects your data

- **Listens only on `127.0.0.1`.** Other devices on your network can't reach it.
- **Answers only its own page.** Every request must carry a loopback `Host`, a same-origin `Origin` and a session token that changes on each start. This blocks other websites and DNS rebinding.
- **Security headers.** A Content-Security-Policy with `connect-src 'self'`, no framing and no referrer.
- **Keys in the keychain.** API keys go to Windows Credential Manager, macOS Keychain or Linux Secret Service when one is available, and are never sent to the browser.
- **Rules are untrusted data.** Packs and rules are validated on load. Regex patterns that could freeze the app are refused, and patterns run in a separate process with a time limit. Document paths can't leave the documents folder.
- **Nothing changes without you.** Routines, MCP apps and the in-app assistant create proposals. You approve each one, and the audit log records it.
- **Backups first.** The database is backed up before every migration and import.

The app doesn't encrypt its data folder. Use disk encryption (BitLocker, FileVault, LUKS) and choose carefully where you sync the folder. See [PRIVACY.md](PRIVACY.md) for what is stored and when the app uses the internet.

## Dependencies

Dependabot proposes Python and GitHub Actions updates, CodeQL scans the code, and CI runs `pip-audit`. Vendored JavaScript and its versions are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
