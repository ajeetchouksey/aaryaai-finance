# AGENTS.md — standing brief for contributors and coding agents

aaryaai finance is a **local-first personal finance manager**: FastAPI + SQLite on `127.0.0.1`, a plain-JavaScript page, country packs in YAML, and an optional AI assistant. Read `README.md` for what it does and `CONTRIBUTING.md` for how rules, packs and the data model work.

## Rules that shape every change

1. **Local-first, no telemetry.** Nothing about a person's finances leaves the computer unless they connected an AI provider or an MCP app. Network access is limited to exchange rates, optional market prices, the daily update check and the AI provider the user chose. New network calls need a line in `PRIVACY.md` and a reason in the PR.
2. **No build step, no CDN.** The frontend is plain JS in `aaryaai_finance/web/`. Third-party code is vendored in `web/vendor/` with its version in `THIRD_PARTY.md`.
3. **Deterministic first.** Document sorting, deadlines, tax checks and categories come from readable YAML rules. AI only adds optional extras, and every screen works with no AI connected.
4. **Suggest, then approve.** Routines, MCP apps and the in-app assistant never change data on their own. They create a proposal, and the person approves it. Every data change and approval is written to the audit log.
5. **Security model.** Every route outside `/static/` must pass the loopback `Host`, same-origin `Origin` and per-start session-token checks in `create_app` (`server.py`). Escape everything that goes into HTML. Keys stay in the system keychain.
6. **Stable data contracts.** `aaryaai_finance/model/core.json` only gains fields or record types in a minor change. Bump its `version`, rely on the backup-then-migrate path, add an old-schema test to `tests/test_model.py`, and record the decision in `docs/adr/`.
7. **No personal data** in code, tests, fixtures or examples. Use the invented data in `site/demo_data.py`.
8. **Estimates, not advice.** Tax and planning output is labelled as an estimate. Every rate and deadline in a pack cites a `source:`.

## Checks before every push

```bash
pip install -e ".[dev,ui]"
ruff check .
pytest -q          # unit and API tests
pytest -m ui       # browser tests on the sample data (needs Playwright + Chromium)
```

Then click through the changed screen at laptop and phone width (360 px), with amounts hidden (Alt+H) and with no AI connected.

## How work is done

- One topic per branch (`fix/<slug>`, `feat/<slug>`, `docs/<slug>`, `chore/<slug>`), Conventional Commits, PRs under about 400 changed lines.
- Structural decisions get a short ADR in `docs/adr/NNNN-title.md`.
- **Releases are manual.** Agents don't bump `__version__`, edit `CHANGELOG.md`, tag or publish. Put plain-words changelog text in the PR body instead.
- The manual acceptance test guide is [docs/uat.md](docs/uat.md).
