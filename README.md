# Inject Monitor

Web UI for diagnosing **memory injections** into LLM requests of [Hermes Agent](https://hermes-agent.nousresearch.com/docs) sessions.

Inject Monitor reads the Hermes session database (SQLite, **read-only**) and shows exactly what was sent to the LLM: the session system prompt, the per-turn timeline (user / assistant / tool calls / tool results / reasoning), and every memory block injected into the request before it left for the API.

> ⚠️ **Works with Hermes Agent only.** The data source is the Hermes session
> database (`state.db`: `sessions`, `messages`, `system_prompts` tables).
> This is not a generic LLM-history viewer and does not support other agent
> frameworks. Also note: if your Hermes setup has no memory provider that
> injects content into requests, there will simply be no injections to show
> (the timeline still works).

## Features

- 🧩 Injections recognized by **configurable tag pairs** (e.g. `<memory-context>…</memory-context>`); nested blocks are parsed recursively and rendered flat, with breadcrumb labels (`memory-context > turn-memory-recall`)
- 🕒 Per-session timeline: user messages, assistant answers, tool calls & results, reasoning blocks, with per-block expand/collapse
- ⬇️ Inject counter badge per session in the session list
- ⚙️ Settings UI: tag pairs, default expansion, panel width, server controls (restart / stop)
- 🔐 **Token-based access**: the API answers 401 without `X-Auth-Token` (or `?token=`); the token is generated on first run, printed to the console, and stored in the file set by `token_file` (chmod 600)
- 🧭 Built-in setup wizard: if the database is missing, the server still starts and the UI helps you point it at the right database
- 🚀 **Zero dependencies**: Python 3 stdlib only (http.server, sqlite3) — nothing to pip-install
- 🔄 Live auto-refresh polling, resizable side panel

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
Inject Monitor v0.32.0
  Token:   /home/<you>/.hermes/inject-monitor-token
  Address: http://127.0.0.1:8092/?token=...
```

Open that URL in a browser (or any URL of the UI — you will get the token login screen; the token is accepted via the form, the `?token=` URL parameter, or the `X-Auth-Token` header).

## Configuration

All runtime settings live in `config.json` next to `monitor.py` (create it from `config.default.json`). Keys:

| Key | Meaning |
|---|---|
| `port` | HTTP port (default `8092`) |
| `host` / `--host` | Bind address (default `127.0.0.1`) |
| `db_path` | Path to Hermes `state.db` (opened **read-only**) |
| `token_file` | Path to the access-token file; relative paths resolve against the monitor folder |
| `sessions_limit` | How many recent sessions the sidebar lists (default `50`) |
| `tag_pairs` | Open/close tag pairs that define what counts as an injection — no defaults are hard-coded |
| `side_width`, `indent_px`, `expand` | UI layout and default expansion preferences |

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
- Every API request requires the token; without it the API answers `401`.
- The database is opened read-only — the monitor never writes to your Hermes data.
- `config.json` and the token file are git-ignored; never commit them.

## Windows helper

`run/inject-monitor.bat` starts the monitor inside WSL from Windows (edit the path inside if your installation differs).

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — internals: data model, parsing, rendering pipeline
- [CHANGELOG.md](CHANGELOG.md) — version history

## License

[MIT](LICENSE)

## Credits

Idea & vibe coding: Oleg Maisak · Coding agent: Lex (via Hermes Agent)
