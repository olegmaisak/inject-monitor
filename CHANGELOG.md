# CHANGELOG — Inject Monitor

Version format: `vMAJOR.FEATURE.BUGFIX (YYYY.MM.DD)`.

This file lists the significant milestones of the project. For the full commit
history see [GitHub commits](https://github.com/olegmaisak/inject-monitor/commits/main).

## v1.0.0 (2026.09.26) — first stable release

Tagged stable release: the API, config keys, and UI behavior described in
[ARCHITECTURE.md](ARCHITECTURE.md) are considered stable. Code identical to
v0.33.0 apart from the version bump.

## Milestones

- **2026-09-04 · MVP (0.01–0.10)** — first working version: stdlib-only HTTP
  server reading the Hermes `state.db` read-only, token authorization, session
  list with collapsible injection blocks (`<memory-context>` from `api_content`),
  system prompt split into sections; content filters and full untruncated
  injection text.
- **2026-09-12 · Universal parsing & tag pairs (v0.12.0)** — injection parsing
  driven by configurable tag pairs (nested pairs rendered flat with
  `parent > child` breadcrumbs); parsing for **all** message roles (not just
  user); `?token=` auto-login; resizable sidebar; per-session filters; full
  English UI.
- **2026-09-12 · Tool-role parsing fixed (v0.16.0)** — tool injections parsed
  from `messages.content` (were invisible: markers live in `content`, not
  `api_content`); open-ended pairs (empty closing marker run to the next
  injection); Settings as a panel view; sidebar width in config.
- **2026-09-20 · Readability & settings (v0.25.0)** — message level indentation
  (config `indent_px`), 💭 Reasoning blocks, default-expansion checkboxes for all
  9 collapsible elements (`expand`), collapsible settings blocks, pair sorting,
  authorship footer.
- **2026-09-20 · External config & onboarding (v0.26.0)** — environment moved
  from code to `config.json` (`db_path`, `token_file`, …) with
  `config.default.json` and first-run creation (defaults never overwrite user
  config); single-window setup wizard when the DB is missing; accurate injection
  counter (parser-based, cached) instead of a rough message count.
- **2026-09-21 · Token onboarding (v0.27.0)** — structured 3-step token
  instructions on the start screen (gate) with the real token-file path; Auto
  button state no longer resets after re-render.
- **2026-09-21 · Standalone deployment (v0.28.x)** — session list limit
  (`sessions_limit`); token file moved into the monitor folder (relative
  `token_file`, legacy `~/.hermes/` path migrated automatically); dead
  agentmemory-proxy code removed — the monitor is fully independent of memory
  providers (parsing is defined by tag pairs only).
- **2026-09-22 · Server controls & incremental render (v0.32.0)** — ⏹ Stop /
  ⟳ Restart server from Settings (execv-based restart with health check);
  incremental session refresh (new messages appended without re-rendering the
  panel); settings block state persisted in config.
- **2026-09-26 · First public release (v0.32.1)** — repository published on
  GitHub (MIT): revised default tag pairs (the 7 blocks the Hermes harness
  builds into the system prompt), English README / ARCHITECTURE / CHANGELOG,
  repository description "Web UI for diagnosing harness & memory injections
  into LLM requests of Hermes Agent sessions".
- **2026-09-26 · Design system (v0.33.0)** — all CSS extracted into
  `static/style.css` with design tokens (palette, typography, spacing), unified
  status-message classes (`setMsg()` + `.status-*`), no inline styles in
  HTML/JS; ARCHITECTURE gained a "Design System" section; README opens with a
  screenshot.
