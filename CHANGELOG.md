# CHANGELOG — Inject Monitor

Version format: `vMAJOR.FEATURE.BUGFIX (YYYY.MM.DD)`.

Historical versions (0.01.00–0.10.00) were recorded in the old scheme (X.YZ) and
are kept here as-is.

## v0.32.1 (2026.09.26)

**Polish for the first public release:**

1. **Default tag pairs revised**: out-of-the-box defaults now cover the blocks the
   Hermes harness itself builds into the system prompt (Hermes system prompt,
   `<available_skills>`, SOUL.md, MEMORY.md, USER.md, Hermes runtime environment,
   Conversation started). Memory-provider tag pairs (e.g. `<memory-context>`) are no
   longer assumed by default — add the pairs of your provider in Settings → Pairs.
2. **Settings footer** now links to the GitHub repository.
3. **README revised**: token setup described as it actually works (token file is
   generated in the monitor folder on first start); what counts as an injection is
   tied to the configured tag pairs, not to a memory provider; config.json is
   documented as never overwritten by defaults; the Windows-helper section and
   `run/` removed from the repository.
4. **ARCHITECTURE.md and CHANGELOG.md** translated to English and depersonalized.
5. Repository description updated: "Web UI for diagnosing harness & memory
   injections into LLM requests of Hermes Agent sessions".

## v0.32.0 (2026.09.22)

**Features (+4 over v0.28.1):**

1. **Server management from UI** (subsystem: buttons + POST `/api/server`): in Settings →
   «Server» above the port, buttons **⏹ Stop server** (with confirm — after stopping,
   the site falls until manual restart) and **⟳ Restart server** (restarts the process
   via `execv` and waits for the fresh `/api/ping` response). Operation status is shown
   next to the buttons (`srv-status`). Both actions require a token (POST, like test-db).
2. **Settings block state saved to config** (`settings_open`, array of block ids in
   order: Server / Data source / Pairs / Default expansion / Session list /
   Message indentation): toggling a block is remembered in JS, the 💾 Save button writes
   to config.json; on opening Settings, blocks are shown as saved.
   Default: all collapsed except **Server** (which is open by default and also when the
   config key is absent — backend `_norm_settings_open`).
3. **Settings panel reorganization**: block order by user importance —
   Server / Data source / Injection trigger tag pairs / Default expansion / Session
   list / Message indentation; the Server block has a new short description
   («Stop / restart the monitor and set the HTTP port…»); below the port — a note
   about clearing browser cache after updating with keyboard shortcuts (Win/Linux:
   Chrome/Edge/Opera and Firefox — Ctrl+F5 / Ctrl+Shift+R; macOS: Chrome/Edge —
   Shift+Cmd+R, Safari — Option+Cmd+R, Firefox — Shift+Cmd+R). ARCHITECTURE.md
   contains a recommendation on block order when extending the panel.
4. **Incremental session refresh**: ⟳ Refresh and auto-tick NO longer re-render the
   entire session. `mergeMessages()` → `incrementalRender()`: existing DOM nodes
   are untouched, new messages are appended at the bottom (by id), chips and system prompt
   are updated in place (only when the hash changes), the filter is reapplied. The same
   approach works for ⟳ Refresh on an open session (`loadSession` uses merge
   when id matches). The sidebar preserves scrollTop on rebuild.

**No increment (cosmetic):** sidebar subtitle changed from «diagnosing memory
injections into LLM requests» to «diagnosing harness injections into AI-agent
sessions» (terminology: harness instead of memory; agent sessions instead of
LLM requests).

## v0.28.0 (2026.09.21)

**Features (+2 over v0.27.0):**

1. **Session list limit** (config `sessions_limit`, default **50**): how many recent
   sessions to load in the sidebar on start/refresh. Configurable in Settings →
   «Session list» (1..500, validated on PUT), applied after Save. The selected
   (open) session is not lost on refresh: `GET /api/sessions?include=<id>`
   adds it at the end of the list if it fell outside the limit (no duplicates).
2. **Token now lives in the monitor folder, not the agent folder**: default `token_file`
   is relative (`inject-monitor-token`) and resolves relative to the monitor.py
   directory — at install time the AI-agent folder is not yet known.
   «Access token file» in config/wizard may be relative (monitor folder),
   `~/...`, or absolute. Migration: if the token file is missing from the monitor folder
   but legacy `~/.hermes/inject-monitor-token` exists — the value is copied (token
   preserved, browser session remains valid). The startup instruction (gate)
   was rewritten into 3 structured steps with the ACTUAL path substituted
   (monitor.py substitutes `__TOKEN_FILE_PATH__` in index.html; the token itself is
   never served over HTTP — only the file path).

## v0.27.0 (2026.09.21)

**Features (+1 onboarding over v0.26.0):**

1. **Token instruction on the start screen (gate)**: where the token comes from
   (printed to console on `python3 monitor.py` start), where it lives
   (`~/.hermes/inject-monitor-token` by default), how to print it (`cat ...`),
   hint to open the start URL with `?token=…` (browser remembers it). In the settings
   wizard, the «Access token file» field has a more detailed explanation. Pressing Enter
   in the token field now submits the form.

**Bugfixes (incidental):**

- The «⟳ Auto» button no longer appears toggled off after the first data
  refresh: `renderMain()` was recreating the entire `#top` panel including the button
  and resetting the `on` class (polling continued working). The button state
  is now restored after each render.
- Tool result header: «📄 result (N chars)» → «Result (N chars)».
- Filter: «⬇️ only with injections» → «⬇️ Only with injections».
- Favicon replaced with black (icons/icon-black.png) — blue was hard to read on the
  tab.

## v0.26.0 (2026.09.20)

**Features (+1 subsystem «config external + onboarding» over v0.25.0):**

1. **Environment parameters moved from code to config.json**: `db_path` (path to
   Hermes state.db, previously hardcoded to `~/.hermes/state.db`), `token_file` (token file),
   `agentmemory_url` (REST agentmemory; priority: config → env `AGENTMEMORY_URL`
   → default). Alongside it is **config.default.json** — the default values source for
   most users; on first run, config.json is created from it
   (if the default file is missing — built-in BUILTIN_DEFAULTS are used).
2. **Settings section «Data source & connections»**: fields for DB path / Token file /
   Agentmemory URL, applied after Save without restart (paths are read
   per-request with a 3 s cache). PUT /api/config now **preserves unknown keys**
   (previously it only overwrote known ones).
3. **Single-window initial setup wizard** (onboarding for new users): if
   config.json is missing or the DB is not found/readable, the server does NOT crash —
   it starts up and serves `GET /api/status`; the UI shows an overlay wizard
   (DB path + Test, token file, agentmemory URL, port, «Save & continue»).
   New `POST /api/test-db` {path} — live path validation.
4. **Injection counter in the session list — actual count**: counts ALL injections per
   session exactly as the parser in the UI does (top-level + nested, each message
   + system prompt + tool results), not «number of messages with api_content».
   Per-session cache (invalidated by max(id)/count and pair changes). Verified:
   session 20260919_235801_93d3d2 shows 85 inj. (was «3»), matches the
   parser on all 200 sessions, 0 discrepancies.
5. **Injection emoji 📥 → ⬇️** everywhere (badges «N inj.», filter «only with
   injections», headers, hint «N chars») — metaphor: down arrow = injection.
6. **Icons**: next to the «Inject Monitor» heading — icon-light-d1d5dd.png
   (static/logo.png); favicon — icon-blue-75a2d8.png (static/favicon.png).
7. **Default expansion fix**: nested `<details>` (Tool call details,
   Tool result details, 💭 Reasoning, inj blocks) now get the **`open` attribute**, not a
   class (a class did not open HTML details). Plus EXPAND and indent are loaded from
   /api/config on page load (previously — only on opening Settings, which caused
   saved states to be ignored on load). Nested element expansion works even when
   the parent is collapsed.
8. **Settings save message** simplified to «✓ Settings saved».

**Bugfixes (incidental):**

- `ThreadingHTTPServer((args.host, args.port))` → `port`: starting without the
  `--port` flag raised TypeError. The systemd unit no longer passes `--port` —
  the port is taken from config.json.
- `api()` in JS: header merging (X-Auth-Token + extra) — previously extra headers
  overwrote the entire token (broke PUT / POST wizard/JSON).

## v0.25.0 (2026.09.20)

**Features (+9 over v0.16.0):**

1. **Message level indentation** (subsystem): left indent by type — System prompt 0,
   User 0, Assistant→Tool call 1, Tool result 2, Assistant 1; pixel value configurable
   in Settings (config.json `indent_px`, default 14, render `level × px + base 20px`).
2. **Message type rename**: 👤 User, 👾 Assistant, 👾 Assistant → 🔧 Tool call,
   🔧 Tool → {name} → Result; unified 🛠️ → 🔧 throughout the interface.
3. **display_kind in message header**: «👾 Assistant | model_switch» — label from
   `messages.display_kind` (state.db) next to the role.
4. **Reasoning block**: «💭 Reasoning N chars» — single block in the message body header.
5. **Default expansion** (subsystem): checkboxes in Settings for all 9 collapsible
   elements (sysprompt/user/assistant/toolcall/toolresult/toolcallDetails/
   toolresultDetails/reasoning/injections); saved in config.json `expand`,
   applied on session open.
6. **Settings reorganization**: collapsible blocks (Server, Message indentation,
   Default expansion, Injection trigger tag pairs) — collapsed by default, header +
   description; «+ Add pair» button inside the pairs block; single Save button at the bottom
   saves all blocks; note removed from panel header; panel stretches full width to the
   right edge (geometry confirmed: panel right = window right).
7. **Tag pair sorting**: ↑↓ buttons for each pair, order saved in config.json.
8. **Authorship block** at the bottom of Settings: «Inject Monitor v… | © 2026 … | MIT».
9. **Site icon**: favicon.png = icons/views (4).png; icon next to the sidebar heading
   «Inject Monitor» instead of 📥 emoji.

**Bugfixes (incidental, no separate increments):**

- Badge «📥 N inj.» in the session list: fixed color (#e6edf3 on dark swatch)
  — previously blended with the blue background of the selected session;
- Reasoning rendered above tool-call, message element geometry unified.

## v0.16.0 (2026.09.12)

**Features (+4 over v0.12.0):**

1. No-close pair rule: a block with an empty closing marker goes from its
   opener to the opening marker of the next injection (or to the end of text).
   Rule description updated in Settings. Test 5b in test_parser_tmp.py.
2. Settings — panel view (third view instead of modal: covers the main column).
3. Sidebar width in config.json (`side_width`): GET /api/config returns it,
   PUT saves it; on load, config value takes priority over localStorage.
4. User messages expanded by default (class="msg open").

**Bugfixes (incidental, no separate increments):**

- Tool injections were not parsed: markers `<tool-memory-recall>` are in
  `messages.content`, not in `api_content` (in state.db: 549 vs 0) —
  the parser now reads content for the tool role. This fixes the subsystem
  «universal parsing» from v0.12.0, which was broken de facto.
- Double-escape `<span class="par">` in «parent > child» labels
  (injBlock no longer escapes the label; callers escape themselves).
- The `loadConfig()` function removed during refactoring left calls in
  `setToken()` and init → JS ReferenceError → 0 sessions on clean load.

## v0.12.0 (2026.09.12)

**Features (11 subsystems over v0.1.0):**

1. Tag pair system (injection parsing by pairs from config.json + `/api/config` GET+PUT +
   trigger tag settings panel + nested pair support with flat «parent > child» render)
2. Universal parsing (parsing for all message roles — not only user +
   system prompt as msg blocks with injections; removed sectional Hermes parsing)
3. Port in settings (config.json `port`, Settings field, applied after
   server restart)
4. sid instead of model (session list: session id instead of LLM model + sid chip in top panel)
5. Sidebar resize (drag handle, default width fits full id)
6. Filters (all checkboxes enabled by default + strict «only with injections» filter
   + filterbar inside the top panel, always visible)
7. Last message time chip (last_msg in sessions API list + chip)
8. Unified message geometry (reasoning first in the body, injections at the end,
   expand/collapse triangle marker, all msg types via `.msg`)
9. Incremental Auto (merge new records without resetting panel state)
10. Token from URL (auto-login via `?token=`)
11. Full UI translation to English (all labels, gate, filters, settings)

Incidental bugfixes: artifact glyphs in JS, broken user-message render branch,
pair cache in tests.

## v0.10.00 — 2026-09-04 (historical entry, old scheme)

First working release + iteration of feedback.

- **0.01.00** — first working MVP release:
  - backend `monitor.py`: HTTP server (stdlib), read-only reading of `~/.hermes/state.db`,
    token authorization, port 8092;
  - API: `/api/sessions`, `/api/sessions/<id>/messages`, `/api/am-search` (proxy to agentmemory REST);
  - frontend: left session panel, hierarchical collapsible blocks with emoji,
    system prompt split into sections, `<memory-context>` injections from `api_content`.
- **+0.05** — feature: checkbox filter over session content (default: only entries with injections).
- **+0.05** — feature: full memory-context text in collapsible block (no truncation).
- Bugfixes included (do not affect the feature-increment count): fixed column narrowing
  (unclosed `.mhead` in renderMsg), removed diff functionality.

