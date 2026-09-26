# Inject Monitor

Web UI for diagnosing **harness & memory injections** into LLM requests of [Hermes Agent](https://hermes-agent.nousresearch.com/docs) sessions.

Inject Monitor reads the Hermes session database (SQLite, **read-only**) and shows exactly what was sent to the LLM: the session system prompt, the per-turn timeline (user / assistant / tool calls / tool results / reasoning), and every block injected into the request before it left for the API — both blocks built by the Hermes harness itself (system-prompt sections, MEMORY.md / USER.md blocks, the skills index, the runtime environment) and injections added by memory providers.

> ⚠️ **Works with Hermes Agent only.** The data source is the Hermes session
> database (`state.db`: `sessions`, `messages`, `system_prompts` tables).
> This is not a generic LLM-history viewer and does not support other agent
> frameworks.

**What counts as an "injection" is defined entirely by your configured tag pairs** (Settings → Pairs). Defaults cover the blocks Hermes builds into the system prompt out of the box; if you run a memory provider, add its tag pairs the same way. This also lets you review the system prompt block by block (persona, memory files, skills, runtime environment) instead of one wall of text.

## Features

- 🧩 Injection blocks recognized by **configurable tag pairs**; nested blocks are parsed recursively and rendered flat, with breadcrumb labels (`memory-context > turn-memory-recall`)
- 🕒 Per-session timeline: user messages, assistant answers, tool calls & results, reasoning blocks, with per-block expand/collapse
- ⬇️ Inject counter badge per session in the session list
- ⚙️ Settings UI: tag pairs, UI settings, server controls (restart / stop)
- 🔐 **Token-based access**: the API answers 401 without `X-Auth-Token` (or `?token=`)
- 🧭 Built-in setup wizard: if the database is missing, the server still starts and the UI helps you point it at the right database
- 🚀 **Zero dependencies**: Python 3 stdlib only (http.server, sqlite3) — nothing to pip-install
- 🔄 Live auto-refresh polling

## Requirements

- Linux or WSL with `python3` (3.8+; stdlib only)
- A [Hermes Agent](https://hermes-agent.nousresearch.com/docs) installation with its session database (default `~/.hermes/state.db`)

## Quick start

```bash
git clone https://github.com/olegmaisak/inject-monitor.git
cd inject-monitor
cp config.default.json config.json   # local, git-ignored config
python3 monitor.py
```

The console prints the address together with the access token:

```
Inject Monitor v0.32.1
  Token:   /path/to/inject-monitor/inject-monitor-token
  Address: http://127.0.0.1:8092/?token=...
```

On first start the monitor **generates a random access token** (`secrets.token_urlsafe`, chmod 600) and stores it in the file set by `token_file` — by default **in the monitor's own folder**. The easiest way in: open the printed URL. Alternatively, the login screen explains the manual flow: copy the token file (e.g. next to your Hermes installation) and paste the value from it into the token field.

## Configuration

All runtime settings live in `config.json` next to `monitor.py`. It is **created on first run** from `config.default.json` and is **never overwritten** afterwards — your settings stay yours. Keys:

| Key | Meaning |
|---|---|
| `port` | HTTP port (default `8092`) |
| `--host` | Bind address (CLI only; default `127.0.0.1`) |
| `db_path` | Path to Hermes `state.db` (opened **read-only**) |
| `token_file` | Path to the access-token file; relative paths resolve against the monitor folder |
| `sessions_limit` | How many recent sessions the sidebar lists (default `50`) |
| `tag_pairs` | Open/close text pairs that define what counts as an injection block. Defaults cover the built-in Hermes system-prompt blocks; memory-provider tags (e.g. `<memory-context>`) are added per provider |
| `side_width`, `indent_px`, `expand` | UI settings |

## Autostart (optional, systemd)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/inject-monitor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now inject-monitor.service
```

The unit assumes the monitor lives in `~/inject-monitor` — adjust `ExecStart`/`WorkingDirectory` if you cloned it elsewhere.

## Security

- The server binds to `127.0.0.1` by default and does not expose data to the network unless you change `--host`.
- Every data API request requires the token; without it the API answers `401` (the `/api/ping` health check is the only exempt endpoint).
- The database is opened read-only — the monitor never writes to your Hermes data.
- `config.json` and the token file are git-ignored; never commit them.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — internals: data model, parsing, rendering pipeline
- [CHANGELOG.md](CHANGELOG.md) — version history

## License

[MIT](LICENSE)

## Credits

Idea & vibe coding: Oleg Maisak · Coding agent: Lex (via Hermes Agent)
