# Inject Monitor — Architecture

Author: Oleg Maisak (idea & vibe coding) · Lex (coding agent)

> Web UI for diagnosing harness & memory injections into LLM requests of Hermes Agent sessions —
> shows what Hermes actually sends to the LLM, including injected context (agentmemory,
> MEMORY.md, USER PROFILE, SOUL), to map the user's query ↔ what the agent sees.
>
> Status: **v0.32.1 (2026-09-26)** — current release; full release history in
> CHANGELOG.md. Earlier milestones: v0.28.1 — agentmemory binding removed (the proxy
> was dead code; monitor is fully provider-independent, injection parsing only from
> state.db by tag pairs, no external memory services); v0.26.0: environment settings extracted from code into config.json + config.default.json,
> single-window setup wizard, honest injection count in session list, emoji ⬇️, icons
> (logo = icon-light-d1d5dd, favicon = icon-blue-75a2d8), Default expansion fixed.
> Version increments follow the `versioning-for-all` skill: vMAJOR.FEATURE.BUGFIX (YYYY.MM.DD).
> Stack: Python stdlib + vanilla JS, zero external dependencies.

---

## 1. Purpose

A diagnostic tool that shows in real time:

1. **What exactly was sent to the LLM** for each request (full text with injections).
2. **Which blocks are harness injections** and which are memory (agentmemory).
3. **Where these injections sit** in the system prompt and in user message bodies.
4. **Diff between turns** — what changed in the injected memory from one step to the next.
5. **Source mapping**: which agentmemory fragment was actually returned for the query (via REST agentmemory proxy).

Usage scenario: open Hermes and this monitor side by side, mapping
"in which request / which injection" the agent sees.

---

## 2. Key Technical Insight (why so little code)

Hermes **already stores byte-fidelity copies of what is sent to the LLM** — this is critical and eliminates
the need for traffic interception / proxies.

### 2.1 `~/.hermes/state.db` (SQLite, primary source)

- **Table `messages`** — full session conversation. Column **`api_content`** is the **single
  source of truth**: the exact text *that was actually sent to the API*, when it differs
  from the "clean" `content` (i.e., when an injection occurred). In the Hermes codebase this is called a "byte-fidelity
  sidecar" (`agent/turn_context.py::compose_user_api_content`, `hermes_state.py`).
  - `content` — "clean" (no injections) user message text;
  - `api_content` — same + appended injections (`\n\n<memory-context>...</memory-context>` etc.);
  - the injection is precisely the **difference `api_content` minus `content`** for user messages.
- **Table `sessions`** — session metadata + `system_prompt_hash` (pointer to system prompt).
- **Table `system_prompts`** — full system prompt by hash. 72K+ characters:
  Persona, SOUL, codex, skill list, MEMORY.md (📜), USER PROFILE (👤), `<agentmemory-context>` (🧠), etc.

### 2.2 When/how memory is injected (what was discovered from the code)

- **System prompt is assembled ONCE per session** and stays **byte-stable** for the entire session
  (required for prompt caching). This means the agentmemory "project" context inside the system prompt
  **does not change** during a session, until a compression/new session occurs.
- **On each user request** — an additional injection into the message body:
  1. prefetch from agentmemory (`/agentmemory/smart-search` based on the user's query), top-5 observations;
  2. wrapped in `<memory-context>...</memory-context>`;
  3. appended to the API copy of the user message (`api_content`).
- **Trigger:** injection happens **at the start of a turn**, based on the **latest user
  text**, and then remains **unchanged for the agent's entire response** (including tool calls) —
  because all subsequent LLM calls in the same turn use the **same** `api_content`
  + the same chain of tool results. However: if the agent *writes to memory* (memory_save/memory_recall)
  and then makes another LLM call within the same turn, memory may change — but the
  `api_content` itself (the "user request") is not recomputed.
- This answers the question: **"injection only at the moment of user request?"** — Yes, for
  harness injection in `api_content`; **"while the agent responds, injection is unchanged?"** — Yes, within
  a single turn. Only between turns is it recomputed for the new request. (Details: `agent/turn_context.py`,
  `agent/memory_manager.py::build_memory_context_block`, `agent/system_prompt.py`.)

### 2.3 `~/.agentmemory/data/state_store.db` (agentmemory, memory source)

- REST server at `:3111` (REST/MCP HTTP). Used via proxy to map "what was searched ↔ what was found."
- Search endpoint: `POST /agentmemory/search {query, limit}` → `{results:[{observation, combinedScore}]}`.
- Not reading its DB directly (iii-engine format), going through the official REST — more reliable.

---

## 3. Components

```
~/inject-monitor/
├── monitor.py            # Backend: HTTP server, state.db reader (read-only), REST proxy, token
├── static/
│   └── index.html        # Frontend: single page, vanilla JS, no build step
├── ARCHITECTURE.md       # this file
```

### 3.1 Backend (`monitor.py`)

- **Stack:** Python stdlib `http.server.ThreadingHTTPServer` — zero dependencies, run via `python3`.
- **DB access:** `sqlite3` with `file:...?mode=ro` (read-only) — does not interfere with a live Hermes,
  does not block WAL.
- **Authorization:** token in `inject-monitor-token` **in the monitor's folder** (default,
  generated on first start, chmod 600; migration copies the value from legacy
  `~/.hermes/inject-monitor-token` if it's still there). Client sends `X-Auth-Token`
  or `?token=`. Static files are unrestricted (no data), API is token-protected. The token file is NEVER
  served over HTTP: `_static()` only serves content from `static/`, paths
  outside it return 401/404; `index.html` only receives the PATH to the file
  (`__TOKEN_FILE_PATH__`) for the gate instructions, not the token value.
- **Port:** `8092` (no conflicts: Hermes 3111/3113, Direktrisa 8081).
- **Endpoints (all JSON):**
  - `GET /` , `GET /index.html` — static (favicon.png, logo.png — unrestricted).
  - `GET /api/ping` — health (no token).
  - `GET /api/status` — server and DB status: `{version, config_exists, db:{path, exists,
    sessions, error}}`; setup wizard driver (token-protected).
  - `GET /api/sessions[?include=<id>]` — list of latest `sessions_limit` sessions
    (config, default 50), desc by last activity, with per-session injection count
    (actual injections, parsed — see 3.5). An open session that falls outside the limit
    is added via the `include` parameter (no duplicates).
  - `GET /api/sessions/<id>/messages` — session messages + system prompt (structured).
  - `GET /api/token` — show current token.
  - `POST /api/test-db` `{path}` — check readability of a state.db path (setup wizard);
    returns `{ok, path, sessions, error}`.
  - `POST /api/server` `{action: "stop"|"restart"}` (v0.32.0) — server management from
    UI (buttons in Settings → Server, require token). `stop`: response sent, then
    server shuts down (threading.Timer + `HTTP_SERVER.shutdown()` + `os._exit(0)` —
    subsequent start only manual from terminal). `restart`: response sent,
    then process restarts **via `os.execv(sys.executable, [python,
    monitor.py, --port])`** — process image replaced, socket closed
    (non-inheritable), no double binding. Global `HTTP_SERVER`/`RUN_PORT`
    are populated in `main()`.
  - `GET /api/am-search` — **removed in v0.28.1** (monitor is memory-provider independent).
  - `GET /api/config` / `PUT /api/config` — read/write `config.json`. PUT starts from the
    current file content and merges the passed keys — **unknown/custom
    keys are preserved**, no "wipe-out". Validation: port 1..65535, side_width 200..2000,
    indent_px 0..120, db_path/token_file — non-empty strings, agentmemory_url — string (can be empty),
    `settings_open` — array of Settings block ids (filtered by `SETTINGS_BLOCK_IDS`).

**config.json** (next to monitor.py) — all environment-dependent parameters:
- `port` (HTTP port), `db_path` (path to Hermes state.db, `~` is expanded), `token_file`
  (access token file; relative path = monitor folder — default
  `inject-monitor-token` next to monitor.py, since at install time the agent folder is
  still unknown), `agentmemory_url` (REST agentmemory, empty = disabled),
  `sessions_limit` (how many recent sessions in the list, default 50), `side_width`,
  `indent_px` (indent level × px), `expand` (default-expansion flags), `tag_pairs`
  (list of `{name, open, close}` — order = render/save order;
  reorderable in UI via ↑↓), `settings_open` (which Settings blocks are expanded:
  array of ids from `SETTINGS_BLOCK_IDS`; default `["server"]` — only Server open).
- Default values are defined in **config.default.json** (source for fresh installs):
  standard Hermes paths (`~/.hermes/state.db`, `~/.hermes/inject-monitor-token`),
  `http://localhost:3111`, 5 standard memory tag pairs for agent plugin. On first
  launch config.json is created from it (fallback — built-in BUILTIN_DEFAULTS in
  monitor.py). All paths are read per-request with a 3s cache; applying
  db_path/token_file/agentmemory_url — without restart (port requires restart).

### 3.2 Extracting injections from `api_content` / `content`

- Injections are recognized **only by tag pairs from `config.json`** (`tag_pairs`):
  `{name, open, close}`. No hardcoded markers — no pairs in config —
  no injections. Universality: doesn't depend on the agent's prompt layout.
- Parsing runs for **each role** (user/assistant/tool):
  - for user/assistant — from `api_content` (exact text sent to the LLM, minus
    the visible `content` prefix);
  - for tool — from `content` (tool results, where injections
    `<tool-memory-recall>` live), since `api_content` doesn't have them.
- Nesting: a pair may contain other pairs; render is flat "parent > child".
- Pairs may lack `close` (no-close): block goes from opener to the next
  opener of any pair or to end of text.
- `display_kind` (from `messages` in state.db) is passed to the UI for a role label.

### 3.3 Record type filter

- Checkbox panel above session content: 📥 injections only / 👤 User /
  👾 Assistant / 🔧 Tool calls / 🔧 Tool results / 🧩 System prompt.
- **All checkboxes enabled by default** (show all types); "injections only" —
  strict filter, hides everything without detected injections.
- Implementation: each record has `data-type` and `data-inj`; `applyFilter()` toggles
  `display` without reloading.

### 3.4 Injection display (full text)

- Each injection is a `<details class="inj">`: collapsed header
  ("🧠 memory-context, N chars — click to expand fully"), on click
  expands **the full block text** (`<pre>` with `white-space:pre-wrap`).
  Full text is always in the DOM — nothing is truncated.

### 3.4 Frontend (`static/index.html`)

- **Layout:** left panel — session list (sorted by latest activity,
  with date separators "Today/Yesterday/date"); right panel — selected session content.
- **Hierarchy (collapsed blogs, expand by branches, large branches with emoji):**
  - `🧩 System prompt` — collapsed; inside `details.sec` by sections: 🎭 Persona, 🦉 Personality,
    📖 codex, 📜 MEMORY, 👤 USER, 🧠 agentmemory-context, 🎯 Skills, 🛠️ Tools, ⏰ etc.
  - each section is a separate `<details>`, expands selectively.
  - `👤 User` — text + nested injection block `🧠 memory-context` (click to expand).
  - `🤖 Assistant` / `🗑️ tool call` (🛠️ with arguments) / `🔧 tool result` — collapsed.
  - diff badge in the turn header shows injection change status.
- **Live update:** "⟳ Refresh" button and "auto" toggle (5s polling).
  **Incremental update (v0.32.0):** existing DOM nodes are untouched — new
  messages are appended at the bottom (`mergeMessages()` → `incrementalRender()` by
  `RENDERED = {sid, ids, sysHash}`), chips and system prompt are updated in place
  (sysprompt — only on hash change), filter is re-applied; ⟳ Refresh for
  an OPEN session uses the same merge path (`loadSession` compares ids). Full
  re-render only remains on session switch. Sidebar preserves `scrollTop` on rebuild.
  `renderMain()` recreates the `#top` panel — button `on` class for Auto
  is restored after every render (`window._auto`).
- No frameworks → works both as a file and via `http://…`.
- **Token onboarding:** gate instructions — 3 structured steps with the real path
  (injected by server): 1) token already generated and saved to
  `<monitor-folder>/inject-monitor-token`; 2) copy the token file to the
  AI agent's folder (e.g. `~/.hermes/`) so the agent can also use it;
  3) copy the token from the file and paste into the field below. Plus tip about the
  startup URL with `?token=` (browser remembers). Enter in the field submits the form. Token rationale:
  session data is sensitive, the token blocks other local
  processes/users; friction is minimal — browser remembers the token.

### 3.5 Injection counter in session list and setup wizard

- **Counter** (badge "⬇️ N inj.") — the total number of injections for the session, computed by
  the same parser that renders blocks inside the session: top-level blocks + their nested
  children, for each active message (api_content of all roles + content for tool)
  plus system prompt. One injection in one message = one, multiple = as many as there are.
  Per-session cache: `session_id -> ((pair signature, max(id) of messages, count(active)),
  count)`; only changed sessions are recomputed (cold start ~0.02-0.8 s,
  auto-refresh doesn't lag). Verified: session 20260919_235801_93d3d2 — 85 inj.,
  matches parser across all 200 sessions.
- **Setup wizard (single window)** appears automatically when the config is not set up,
  the path is missing, or the DB is unreadable: the server starts even without a DB (no crash);
  the UI shows a wizard overlay based on `GET /api/status`: DB path (+ Test button →
  `POST /api/test-db`), token file, agentmemory URL, port, "Save & continue". After
  saving — re-check status → session list. Tag pairs are edited later in
  ⚙ Settings.

### 3.6 Icons and Default expansion

- Icons: next to the "Inject Monitor" heading — `static/logo.png` (icon-light-d1d5dd.png),
  light, readable on a dark panel; `favicon` — `static/favicon.png` (icon-black.png,
  black — blue was pale on the tab). Injection emoji — **⬇️** (down arrow =
  "injected into the request"), everywhere instead of 📥.
- Default expansion: nested `<details>` (Tool call details, Tool result details,
  💭 Reasoning, inj-blocks) get the **`open` attribute** (class `open` does not expand
  HTML `<details>`; this trick only works for div-messages). EXPAND and indent
  are loaded from `/api/config` on page start (previously — only when opening
  Settings, so saved states were ignored on load). Nested element
  expansion works even when the parent is collapsed (DOM attribute doesn't depend
  on parent visibility).

---

## 4. Agreed Decisions

1. **Data source:** only `state.db` (read-only) + REST agentmemory. No traffic interception in MVP.
2. **Left panel** instead of a dropdown — quick session switching.
3. **Hierarchical collapsible blocks** with emoji per type; expand only the needed branch.
4. ~~**Diff between turns**~~ — **removed** (deemed unnecessary).
5. **Russian interface** (all UI texts, except technical code markers).
6. **Portability:** stdlib-only backend, vanilla JS frontend, zero npm/pip dependencies.
7. **Security:** token authorization by default (required for all components),
   bind to 127.0.0.1.
8. **.bat on the desktop** for launching from Windows (per convention).
9. **Settings panel block order (recommendation, v0.32.0):** when adding to
   Settings, keep **important/frequently used** above, and rare settings
   ("set once and forget") below. Current order: Server / Data source /
   Injection trigger tag pairs / Default expansion / Session list / Message
   indentation (author's block — last, outside the block list). Collapse
   state of blocks is saved in config (`settings_open`); default — all
   collapsed except Server.

---

## 5. Status & Plan (2026-09-04)

- [x] Backend: read-only state.db, session/message/system prompt API, token.
- [x] Frontend: left panel, hierarchical blocks, injections (full text on click).
- [x] Proxy `/api/am-search` to agentmemory REST.
- [x] API test on real data (133 sessions, real injections found).
- [x] UI test in real Chrome (CDP): token gate, session render, injections — OK.
- [x] v0.10.00: checkbox filter (default: injections only), full memory-context text,
      diff removed, column narrowing fixed (unclosed `.mhead`).
      Version per `versioning-rules`: 0.01.00 (first release) → +0.10 (2 features) → **0.10.00**.
- [ ] .bat desktop shortcut — created but not verified.
- [ ] Registered in SCRIPTS-INDEX.md — done.

---

## 6. Running

```bash
cd ~/inject-monitor
python3 monitor.py --port 8092
# open http://127.0.0.1:8092/ , enter token from ~/.hermes/inject-monitor-token
```

From Windows — via `.bat` on the desktop (see section 4.8).

The server runs as a **regular background process** (`python3 monitor.py --port 8092`),
no systemd unit. Restart after backend edits: `kill <pid>` and re-launch;
frontend (`static/index.html`) is read from disk on each request — no restart needed.

---

## 7. Known MVP Limitations

- Does not show intermediate LLM calls within a single tool loop (only what's in `state.db`).
  For byte-fidelity of each call, an interceptor between Hermes and the provider is needed (post-MVP).
- System prompt — only the latest session hash; if the session was compressed, the current one is used.
- agentmemory REST must be alive (`:3111`), otherwise `/api/am-search` returns `{"available": false}`.