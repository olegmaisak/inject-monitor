# Inject Monitor — Architecture

Web UI for diagnosing **harness & memory injections** into LLM requests of Hermes Agent sessions.
Reads the Hermes session database (SQLite, read-only) and shows what was actually sent to the LLM,
including both harness-built blocks (system-prompt sections, MEMORY.md/USER.md, skills, runtime
environment) and memory-provider injections.

**Version:** 1.1.0

---

## Purpose

Diagnostic web UI that reads the Hermes session state database (SQLite, read-only via
`file:...?mode=ro`) and visualises every block injected into LLM requests — both harness-built
blocks and memory-provider injections. Shows session system prompts, per-turn timelines
(user/assistant/tool calls/results/reasoning), and a breakdown of the final request text as the
LLM received it.

The monitor is **provider-independent**: injection recognition is driven entirely by configurable
tag pairs, not by any specific agent's prompt layout or memory service.

---

## Data Model

The sole data source is `~/.hermes/state.db` — the Hermes Agent session database. The monitor
opens it read-only and never writes to it.

### Tables

**`sessions`** — session metadata: `id`, `title`, `model`, `started_at`, `cwd`,
`system_prompt_hash`.

**`messages`** — per-turn records:
- `role` — one of `user`, `assistant`, `tool`.
- `content` — clean visible text. User-message content may be a `\x00json:`-prefixed JSON string
  (decoded transparently by the monitor).
- `api_content` — the exact byte-level text sent to the LLM. For user messages this equals
  `content` plus appended injection blocks. This is the primary source for injection detection.
- `tool_calls` — JSON array of tool calls with `{id, name, arguments}`.
- `tool_name`, `tool_call_id` — metadata for tool-result messages.
- `reasoning` — assistant reasoning block text.
- `display_kind` — optional role-label override.
- `active` — flag; only active records are displayed.

**`system_prompts`** — full system prompt text keyed by `hash` (SHA256). The same prompt is
reused across sessions with identical configurations (immutable per hash).

---

## Injection Parsing

Injections are recognised **solely** by tag pairs from `config.json` (`tag_pairs`). Each pair has:
- `name` — UI label (e.g. `"memory-context"`).
- `open` — string that marks the start of a block.
- `close` — closing string; empty means the block runs from its opener to the next opener of
  any pair or the end of text.

### Per-role parsing

- `user` / `assistant` — parsed from `api_content` (the exact request text). The clean `content`
  prefix is separated; only the injected suffix is scanned for blocks.
- `tool` — parsed from `content` (tool results, where tool-memory injections live). `api_content`
  does not carry tool injections.

### Nesting

If an opening marker of another pair occurs inside a recognised block, child blocks are extracted
into a `children` array. The parent text remains complete. The UI renders such blocks flat with
breadcrumb labels separated by `>`, e.g. `memory-context > turn-memory-recall`.

### No-close pairs

A pair without a close marker captures text from its opener to the next opener of any pair (or
end of text). This handles section headers that consume everything until the next heading.

### Example

With pairs `{name: "memory-context", open: "<memory-context>", close: "</memory-context>"}` and
`{name: "turn-memory-recall", open: "<turn-memory-recall>", close: "</turn-memory-recall>"}`, a
block containing both produces one parent with one child.

### Independence

The parser is universal. It works for any agent's prompt layout — only the configured tag pairs
need to match. No pair means no injection detection.

---

## UI Structure

Single-page HTML application in `static/index.html`. Vanilla JavaScript, no frameworks, no build
step.

### Layout

- **Left panel** — session list, newest-first, with date separators (Today/Yesterday/full date).
  Each entry shows title, model, timestamp, and an injection badge (`⬇️ N inj.`).
- **Center timeline** — expandable message blocks per role:
  - `🧩 System prompt` — collapsed by default; sections with labelled injection blocks.
  - `👤 User` — text with nested `🧠` injection blocks.
  - `👾 Assistant` — response text, optional `💭 Reasoning`, tool-call blocks.
  - `🔧 Tool call` / `🔧 Tool result` — collapsed on open; details expand inside.
  - Injections render as `<details class="inj">` with full block text in `<pre>`.
- **Bottom bar** — persistent strip under the timeline with a single
  `⬇ Scroll to bottom` button: an instant jump to the latest messages. It is a
  layout strip, not an overlay (`#maincol` wraps `#main` + `#bottombar`): it
  never covers messages, the sticky header or the sidebar, and it survives
  `renderMain()` re-renders.

### Settings panel

Accessible from the toolbar. Blocks in this visual order (HTML order):
- **Server** — status, stop/restart buttons.
- **Data source** — DB path with Test button.
- **Injection trigger tag pairs** — add, edit, remove, reorder.
- **Sessions list** — `sessions_limit`.
- **Session panel** — short display options of the open session: Auto-on-open
  default (`auto_default`) and message indentation (`indent_px`).
- **Default expansion of collapsible elements** — per-message-type collapse
  defaults.

Rules:
- Blocks whose open/collapsed state is persisted are listed in
  `SETTINGS_BLOCK_IDS` in the UI; a new block id must be registered there
  (unknown ids are filtered out on load, so an unregistered block loses state).
- **Large blocks stay separate.** A Settings block with many options inside
  (visually large, e.g. *Default expansion of collapsible elements*) remains
  its own block even when its options logically belong to the session panel.
- Inside one block, logically distinct settings are separated by a hairline
  divider `hr.sep` (see Design System → Settings blocks and separators).

### Filtering

Checkbox bar: injections only, user, assistant, tool calls, tool results, system prompt. All
enabled by default. "Injections only" hides every block without detected injections. Client-side
toggle via `data-type` / `data-inj` attributes.

### Auto-refresh

Toggle button (5 s polling). Incremental merge: existing DOM nodes are preserved; new messages
are appended at the bottom. Full re-render only on session switch.

---

## API Endpoints

All endpoints return JSON. Every data endpoint requires `X-Auth-Token` header, `?token=` query
parameter, or a submitted login form. The server answers `401` when the token is missing or wrong.

### GET (no token required)

| Path | Purpose |
|---|---|
| `/`, `/index.html` | Serve `static/index.html` |
| `/favicon.png`, `/logo.png` | Static resources (served freely from `static/`) |
| `/api/ping` | Health check — `{"ok": true, "version": "..."}`. Only endpoint exempt from auth. |

### GET (token required)

| Path | Purpose |
|---|---|
| `/api/sessions[?include=<id>]` | Latest `sessions_limit` sessions, descending by last activity. Each entry includes its injection count. An open session outside the limit is appended via `include`. |
| `/api/sessions/<id>/messages` | Session metadata, system prompt, all active messages with parsed injections. |
| `/api/status` | Server version, config existence, DB health — drives the setup wizard. |
| `/api/config` | Current config values (port, sessions_limit, db_path, token_file, side_width, tag_pairs, indent_px, expand, settings_open). |
| `/api/token` | Current access token (for debugging). |

### POST (token required)

| Path | Purpose |
|---|---|
| `/api/test-db` | `{"path": "..."}` — validates a state.db path; returns `{ok, path, sessions, error}`. |
| `/api/server` | `{"action": "stop"|"restart"}` — server lifecycle. `stop` calls `HTTP_SERVER.shutdown()` + `os._exit(0)`. `restart` replaces the process via `os.execv(sys.executable, [python, monitor.py, --port])`. Response sent before action (400 ms timer). |

### PUT (token required)

| Path | Purpose |
|---|---|
| `/api/config` | Write `config.json`. Merges with current file content — unknown/custom keys are preserved. Validates ranges and types. Invalidates internal caches on write. |

---

## Configuration

All environment settings live in `config.json` next to `monitor.py`.

| Key | Default | Description |
|---|---|---|
| `port` | `8092` | HTTP port; overridable via `--port` CLI flag. |
| `--host` | `127.0.0.1` | Bind address (CLI-only, not in config file). |
| `db_path` | `~/.hermes/state.db` | Path to Hermes session database. |
| `token_file` | `inject-monitor-token` | Token file path; relative values resolve against the monitor folder. |
| `sessions_limit` | `50` | Max sessions in the sidebar list (1–500). |
| `side_width` | `320` | Left panel width in pixels (200–2000). |
| `indent_px` | `28` | Indentation per level in pixels (0–120). |
| `auto_default` | `false` | Auto refresh button is ON when a session opens. |
| `expand` | All `false` except `user` | Default expansion per message type. |
| `settings_open` | `["server"]` | Settings blocks open on page load. |
| `tag_pairs` | 7 built-in pairs | Injection recognition markers (see Injection Parsing). Built-in defaults cover Hermes system-prompt sections: Hermes system prompt, `<available_skills>`, SOUL.md, MEMORY.md, USER.md, Hermes runtime environment, Conversation started. |

On first start `config.json` is created from `config.default.json` (if present) or from
`BUILTIN_DEFAULTS` in `monitor.py`. The file is **never overwritten** after creation — user
settings persist across updates and `git pull`.

Port, `side_width`, `indent_px`, `auto_default`, `sessions_limit`, `db_path`, `token_file`,
`tag_pairs`, `expand`, and `settings_open` can be changed via the Settings panel. Port change
requires a restart.

**Rule — Settings changes vs shipped defaults.** When a Settings block or option is added or
changed in the UI code, the default MUST be reflected in **both** default carriers:
`config.default.json` (the user-visible copy created on first run) and `BUILTIN_DEFAULTS` in
`monitor.py` (the fallback if the file is missing). They are kept in sync. Before finishing the
change, check what a fresh installation gets — a UI option without a shipped default is an
incomplete change.

---

## Token

- Generated on first start via `secrets.token_urlsafe(24)` → 32 characters of base64 URL-safe
  text.
- Stored in the configured `token_file` (default `inject-monitor-token` in the monitor's own
  folder) with `chmod 0o600`.
- Printed to console on startup as part of the access URL.
- Cached in memory for 5 seconds to avoid repeated file reads.
- Migrates from legacy path `~/.hermes/inject-monitor-token` if the new file does not yet exist
  — browser sessions stay valid after migration.
- Required for every data API call (`X-Auth-Token` header or `?token=` query parameter). Static
  files (HTML, images) are served without a token.

---

## Deployment

Example **systemd user unit** in `deploy/inject-monitor.service`:

```ini
[Unit]
Description=Inject Monitor — memory injection diagnostics UI for Hermes Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/inject-monitor/monitor.py
WorkingDirectory=%h/inject-monitor
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

The unit assumes the monitor is cloned to `~/inject-monitor`; adjust `ExecStart` and
`WorkingDirectory` if installed elsewhere.

Enable and start:

```bash
cp deploy/inject-monitor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now inject-monitor.service
```

After code changes, restart:

```bash
systemctl --user restart inject-monitor.service
```

The server binds to `127.0.0.1` by default. Change `--host` to expose to the network (not
recommended without a reverse proxy or firewall).

---

## Design System

All styling lives in `static/style.css` — no inline CSS in HTML or JS. The design
language is a dark GitHub-style palette with a compact, monospace-accented look.

### Color palette (CSS custom properties)

| Token | Hex | Usage |
|---|---|---|
| `--bg` | `#0d1117` | page background |
| `--panel` | `#161b22` | sidebar, modal cards, panels |
| `--panel2` | `#1c212a` | hover surfaces |
| `--border` | `#30363d` | borders, separators, scrollbar thumb |
| `--text` | `#e6edf3` | primary text |
| `--muted` | `#8b949e` | secondary text, labels, hints |
| `--accent` | `#58a6ff` | active session, session ids, focus, drag handle, hover/outline accent |
| `--accent-strong` | `#1f6feb` | solid primary buttons (darker accent for white-text contrast) |
| `--green` | `#3fb950` | success status, inject counters |
| `--red` | `#f85149` | errors |
| `--yellow` | `#d29922` | warnings |
| `--purple` | `#a371f7` | reserved semantic accent |
| `--cyan` | `#39c5cf` | reserved semantic accent |

Derived overlays: `rgba(13,17,23,.55)` chip background, `rgba(255,255,255,.18)`
chip border, `rgba(255,255,255,.85)` text on accent, `rgba(57,197,207,.06)` and
`rgba(163,113,247,.06)` tinted block backgrounds.

Rules: colors are picked from the tokens only; no new hex values in components.
Status semantics: green = success, red = error, yellow = warning, muted =
neutral/progress. Links inside UI copy use the inherited text color with an
underline (`a.footer-link`), not the browser default blue.

### Typography

- UI font: `--font-ui` (`-apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif`)
- Mono font: `--font-mono` (`ui-monospace, Consolas, monospace`) — session ids,
  code, token paths, prompt text
- Size scale: `--fs-xs` 11px (labels, meta, dates), `--fs-s` 12.5px (base body
  and settings text), `--fs-m` 13px (prompt/pre text), `--fs-l` 15px (h1/h2 and
  modal titles). Line-height: 1.5 base, 1.3 compact (session titles), 1.55
  relaxed (notes).

### Spacing

Scale `--sp-1` 4px, `--sp-2` 8px, `--sp-3` 12px, `--sp-4` 20px. Typical paddings:
session rows 10px 12px, page header 12px 20px, gaps 8px. Border radius follows
existing components (4px small controls, 8px chips, 14px modal cards).

### Buttons and hover

Two button families, one hover rule each (no per-button exceptions):

- **Solid** (the screen's primary action): `⟳ Refresh` (`--purple`), `💾 Save`
  and gate sign-in (`--accent-strong` — darker accent, kept for white-text
  contrast). Hover: `filter: brightness(1.18)`.
- **Outline/ghost** (secondary actions): `Auto`, `⚙ Settings`, `.btn.ghost`,
  `Scroll ⬆` / `Scroll ⬇` (`--panel2` background, `--border` outline). Hover:
  border + text turn `--accent`; the Auto "on" state keeps its green
  (`:hover:not(.on)`).

**One primary button per screen.** Each view has exactly one visually dominant,
bright "target" button (session view — `⟳ Refresh`; settings — `💾 Save`; gate —
sign-in). Every other control, including the bottom-bar scroll buttons, must
stay quiet (outline family or muted fill) and never outshine the primary one.
Do not add a second loud accent button to a view.

The bottom bar is a status-bar-like strip: its buttons (`Scroll ⬆` / `Scroll ⬇`)
are right-aligned (`justify-content:flex-end`), and its right padding adds
`--scrollbar-w` so their right edge lines up with the toolbar buttons above —
those sit inside the scrollable timeline and are inset by its scrollbar.

### Settings blocks and separators

Inside one Settings block, logically distinct settings are separated by a
hairline divider `hr.sep` (border-top `--border`, 12px vertical margins) —
no heading, just the line. The option label is the prominent part
(`.exrow` / `.portrow`, `--fs-m`); its explanation is the dim small line
`.opt-note` (`--fs-xs`, `--muted`) placed under the option. The
label-prominent / hint-dim hierarchy applies everywhere settings are shown.

**Naming options.** A setting's label must be clear and unambiguous yet compact
(short line, no jargon): `Message nesting indent (px)`, not `Indent per level`.
The dim description under the label may be long and detailed — move the
explanation there, not into the label.

### Geometry, alignment and the grid

**When adding any new element, check its geometry against the existing
elements** — edges, paddings, heights, baselines — and snap to the implied grid
wherever possible:

- Horizontal edges align with the block gutter: content, cards, toolbars and
  bars use the same 20px side gutter (`--sp-4`). A control in a bar aligns its
  right/left edge to the same gutter as the neighbouring toolbar.
- Mind the scroll container: anything *inside* the scrollable area is inset by
  the scrollbar (`--scrollbar-w`, 10px with `scrollbar-width:thin`), anything
  *outside* it is not — compensate explicitly (see `#bottombar`).
- Vertical rhythm uses the spacing scale (`--sp-1..4`); a new control inside a
  row keeps that row's padding and height.
- Verification: measure the new element's `getBoundingClientRect()` against its
  neighbours — a 1px difference is a defect to fix, not noise.

### Status messages and visibility

JS never sets colors or display directly:

- `setMsg(el, text, kind)` with `.status-ok` / `.status-err` / `.status-warn` /
  `.status-info` classes for all status lines (settings save, setup wizard,
  server controls).
- `.hidden` utility for show/hide of ordinary blocks; `#gate.open` /
  `#setup.open` for modals (CSS defaults keep them closed).
- The only permitted runtime style is the config-driven per-level indent
  (`margin-left` computed from `indent_px`).

### Emoji conventions

| Emoji | Meaning |
|---|---|
| ✓ | success / connected |
| ✗ | error / failure |
| ✕ | close / delete row |
| ⬇️ | injection count badge |
| 🧩 | tag pairs / injections / system prompt |
| 👤 | user message |
| 👾 | assistant message |
| 🔧 | tool call / tool result |
| 💭 | reasoning |
| ⚙ | settings |
| ⟳ | restart |
| ⏹ | stop |
| 🔐 | auth / token |
| 💾 | save |
| ⬆ / ⬇ | bottom-bar navigation (Scroll ⬆ / Scroll ⬇, text-style arrows — same style for both) |

Rules: a status emoji pairs with the matching status color (✓+green, ✗+red);
one emoji per control; emoji carry meaning, they are not decoration.

### Extending

New styling goes to `static/style.css` and uses the tokens above. Inline
`style=""` attributes and JS `style.*` assignments are not allowed.

---

## Limitations

- **No byte-level LLM call capture.** The monitor reads only what Hermes wrote to `state.db` —
  the final request text. Intermediate LLM calls within a single tool loop are not captured
  unless Hermes records them.
- **Session compression.** State.db may compress old sessions; the earliest messages are lost
  after compression. The monitor shows only what remains.
- **No injection history.** Injections are parsed from the current session state. There is no
  per-turn historical diff — only the current render of each message.
- **Read-only.** The monitor never writes to the Hermes database, configures Hermes, or starts
  Hermes processes.

---

## Credits

Idea & vibe coding: Oleg Maisak · Coding agent: Lex (via Hermes Agent)
