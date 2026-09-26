#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inject Monitor — web UI for diagnosing memory injections into Hermes LLM requests.

Author: Oleg Maisak (idea & vibe coding) + Lex (coding agent, via Hermes Agent)
Version: 1.0.0
Date: 2026-09-26

Purpose:
  Reads the Hermes session database (SQLite, READ-ONLY) and shows:
    - session system prompt (fixed per session), treated as a message-type
      block with injections inside;
    - per-turn timeline: user/assistant messages, tool calls, tool results;
    - injections: memory blocks injected into LLM requests (stored in
      messages.api_content — the exact byte-level text sent to the LLM).

  Injections are recognized ONLY by tag pairs defined in config.json
  (see the "Config" section below). No defaults are hard-coded: if the
  config defines no pairs, nothing is treated as an injection. The app is
  universal and does not depend on any specific agent's prompt layout.

Launch:
    python3 monitor.py [--port 8092]
  Port resolution: --port CLI flag > "port" key in config.json > 8092.
  The port can also be changed in the web Settings panel (stored in
  config.json, applied on restart).

Config:
    All environment-dependent settings live in config.json next to
    monitor.py: port, db_path, token_file, sessions_limit, side_width,
    indent_px, expand (default expansion), tag_pairs.
    The monitor is memory-PROVIDER-INDEPENDENT: injections are recognized
    by tag pairs from the config and read from the agent's session DB only.
    On first run config.json is created from config.default.json
    (shipped defaults suitable for most users); if that file is missing,
    built-in defaults (BUILTIN_DEFAULTS) are used instead.
    If the database path is wrong or the DB is missing, the server still
    starts and the web UI opens a single-window setup wizard.

Auth:
    Token is generated on first run into the configured token file
    (default ~/.hermes/inject-monitor-token, chmod 600). The client passes
    it via the X-Auth-Token header or ?token=.
    Without a token the API answers 401. Static files (index.html) are
    served freely — they contain no data.
"""

import argparse
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

APP_VERSION = "1.0.0"

# ── Paths ───────────────────────────────────────────────────────────────────
HOME = Path.home()
SCRIPT_DIR = Path(__file__).parent
STATIC_DIR = SCRIPT_DIR / "static"
CONFIG_FILE = SCRIPT_DIR / "config.json"
DEFAULT_CONFIG_FILE = SCRIPT_DIR / "config.default.json"
DEFAULT_PORT = 8092

# Left indent per message type: level × indent_px
# (0 = System prompt/User, 1 = Assistant/Assistant→tool call, 2 = Tool result)
DEFAULT_INDENT_PX = 14

# Default expansion state of collapsible UI elements (Settings → Default expansion)
DEFAULT_EXPAND = {
    "sysprompt": False,
    "user": True,
    "assistant": False,
    "toolcall": False,
    "toolresult": False,
    "toolcallDetails": False,
    "toolresultDetails": False,
    "reasoning": False,
    "injections": False,
}

# Built-in defaults for a fresh installation (config.default.json is the
# user-visible copy of these; BUILTIN_DEFAULTS is the fallback if the file
# itself is missing). Values are chosen to suit most users:
#   - the built-in Hermes system-prompt blocks recognized out of the box
#     (memory-provider tags, e.g. <memory-context>, are added per provider
#     via Settings -> Pairs).
BUILTIN_DEFAULTS = {
    "port": DEFAULT_PORT,
    "db_path": "~/.hermes/state.db",
    # Relative token_file values resolve against the monitor's own folder:
    # at install time the AI-agent folder location is unknown, so the token
    # is generated here first and can be copied to the agent folder later.
    "token_file": "inject-monitor-token",
    "sessions_limit": 50,
    "side_width": 320,
    "indent_px": DEFAULT_INDENT_PX,
    "expand": DEFAULT_EXPAND,
    "tag_pairs": [
            {
                    "name": "Hermes system prompt",
                    "open": "You run on Hermes Agent (by Nous Research)",
                    "close": ""
            },
            {
                    "name": "<available_skills>",
                    "open": "<available_skills>",
                    "close": "</available_skills>"
            },
            {
                    "name": "SOUL.md",
                    "open": "# Hermes Agent Persona",
                    "close": ""
            },
            {
                    "name": "MEMORY.md",
                    "open": "MEMORY (your personal notes)",
                    "close": ""
            },
            {
                    "name": "USER.md",
                    "open": "USER PROFILE (who the user is)",
                    "close": ""
            },
            {
                    "name": "Hermes runtime environment",
                    "open": "# Hermes runtime environment",
                    "close": "<!-- End Hermes runtime environment -->"
            },
            {
                    "name": "Conversation started",
                    "open": "Conversation started:",
                    "close": ""
            }
    ],
}

# Prefix of JSON-encoded content in messages.content (see hermes_state.py)
_CONTENT_JSON_PREFIX = "\x00json:"

# Token is cached for 5 seconds to avoid reading the file on every request
_token_cache = {"value": None, "ts": 0.0, "path": None}


def ensure_default_config():
    """Create config.json on first run from config.default.json (or built-ins)."""
    if CONFIG_FILE.exists():
        return
    try:
        if DEFAULT_CONFIG_FILE.exists():
            CONFIG_FILE.write_text(
                DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            CONFIG_FILE.write_text(
                json.dumps(BUILTIN_DEFAULTS, ensure_ascii=False, indent=2),
                encoding="utf-8")
        print(f"Created default config: {CONFIG_FILE}")
    except OSError as e:
        print(f"WARN: cannot create {CONFIG_FILE}: {e}")


def read_config_file() -> dict:
    """Raw config.json content as a dict; {} if missing or broken."""
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# Config cache: re-read at most once per 3 seconds (Settings writes the file)
_cfg_cache = {"value": None, "ts": 0.0}


def get_config(force: bool = False) -> dict:
    """Merged config: BUILTIN_DEFAULTS deep-merged under config.json values."""
    now = time.time()
    if force or _cfg_cache["value"] is None or now - _cfg_cache["ts"] > 3:
        file_cfg = read_config_file()
        out = json.loads(json.dumps(BUILTIN_DEFAULTS))  # deep copy
        for k, v in file_cfg.items():
            if k == "expand" and isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
        _cfg_cache["value"] = out
        _cfg_cache["ts"] = now
    return _cfg_cache["value"]


def invalidate_config_cache():
    _cfg_cache["value"] = None


def get_db_path() -> Path:
    """Configured path to the Hermes session database (state.db)."""
    p = str(get_config().get("db_path") or BUILTIN_DEFAULTS["db_path"]).strip()
    if not p:
        p = BUILTIN_DEFAULTS["db_path"]
    return Path(os.path.expanduser(p))


def get_token_file() -> Path:
    """Configured path to the access-token file.

    Relative values resolve against the monitor's own folder (so the token
    lives next to monitor.py by default); "~" expands to the user home; an
    absolute path is used as-is.
    """
    p = str(get_config().get("token_file") or BUILTIN_DEFAULTS["token_file"]).strip()
    if not p:
        p = BUILTIN_DEFAULTS["token_file"]
    if p.startswith("~"):
        return Path(os.path.expanduser(p))
    path = Path(p)
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path


def get_token() -> str:
    """Access token: read/create the configured token file."""
    now = time.time()
    token_path = get_token_file()
    if (_token_cache["value"] and _token_cache["path"] == str(token_path)
            and now - _token_cache["ts"] < 5):
        return _token_cache["value"]
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if not token:
            token = secrets.token_urlsafe(24)
            token_path.write_text(token, encoding="utf-8")
            token_path.chmod(0o600)
    else:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(24)
        token_path.write_text(token, encoding="utf-8")
        token_path.chmod(0o600)
    _token_cache["value"] = token
    _token_cache["ts"] = now
    _token_cache["path"] = str(token_path)
    return token


def db_connect() -> sqlite3.Connection:
    """Open state.db in read-only mode (does not disturb the live Hermes)."""
    con = sqlite3.connect(f"file:{get_db_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def decode_content(raw) -> object:
    """Decode messages.content (may be a \\x00json:-prefixed JSON string)."""
    if isinstance(raw, str) and raw.startswith(_CONTENT_JSON_PREFIX):
        try:
            return json.loads(raw[len(_CONTENT_JSON_PREFIX):])
        except (json.JSONDecodeError, TypeError):
            return raw
    return raw


# ── Config: injection trigger tag pairs ─────────────────────────────────────
#
# Injections are defined ONLY by pairs from config.json (next to monitor.py):
#   {"tag_pairs": [
#       {"name": "memory-context", "open": "<memory-context>", "close": "</memory-context>"},
#       ...
#   ]}
# No defaults are active unless present in the config: no pairs in config
# means no injections. The pair name is used as the "kind" in the UI.

def load_tag_pairs():
    """Read injection tag pairs from config.json. [] if the file/pairs are missing."""
    pairs = get_config().get("tag_pairs")
    out = []
    for p in pairs if isinstance(pairs, list) else []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        open_m = str(p.get("open", ""))
        close_m = str(p.get("close", ""))
        if name and open_m:
            out.append({"name": name, "open": open_m, "close": close_m or None})
    return out


def load_port() -> int:
    """Read the port from config.json; DEFAULT_PORT if absent/invalid."""
    port = get_config().get("port", DEFAULT_PORT)
    try:
        port = int(port)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def load_sessions_limit() -> int:
    """How many recent sessions to show in the sidebar (config sessions_limit)."""
    v = get_config().get("sessions_limit", 50)
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 50
    return v if 1 <= v <= 500 else 50


def get_tag_pairs():
    return load_tag_pairs()


def invalidate_pairs_cache():
    invalidate_config_cache()


def _norm_expand(v):
    """Normalize the 'expand' config value: merge with defaults."""
    out = dict(DEFAULT_EXPAND)
    if isinstance(v, dict):
        for k in out:
            if isinstance(v.get(k), bool):
                out[k] = v[k]
    return out


# Settings panel block ids (UI <details> blocks), in display order.
SETTINGS_BLOCK_IDS = ["server", "datasource", "pairs", "expansion",
                      "sessionlist", "indent"]
# Default open state of the Settings blocks: only Server is expanded.
DEFAULT_SETTINGS_OPEN = ["server"]


def _norm_settings_open(v):
    """Normalize the 'settings_open' config value to known block ids."""
    if not isinstance(v, list):
        return list(DEFAULT_SETTINGS_OPEN)
    out = []
    for item in v:
        if isinstance(item, str) and item in SETTINGS_BLOCK_IDS and item not in out:
            out.append(item)
    return out


def extract_injections(api_content: str, clean_content: str):
    """Split api_content into a clean part and a list of injection blocks.

    Injections are ONLY the blocks recognized by pairs from the config.
    Returns (clean, injections: [{kind, start, text, children: [...]}]).

    Nesting: if an opening marker of another pair occurs inside a recognized
    block, child blocks are extracted into "children" (flat list in the UI);
    the parent block text is NOT cut (it stays complete).
    """
    pairs = get_tag_pairs()
    if not api_content or not isinstance(api_content, str) or not pairs:
        return "", []
    # If api_content starts with the clean content — separate it
    base = ""
    if clean_content and isinstance(clean_content, str) and api_content.startswith(clean_content):
        base = clean_content
        rest = api_content[len(clean_content):]
    else:
        rest = api_content

    # Build a flat list of blocks (in order of appearance, with nesting level)
    flat = []  # [{kind, text, depth, parent}]
    def scan(segment, depth, parent):
        pos = 0
        while True:
            # nearest opening marker of any pair
            found = None
            for p in pairs:
                idx = segment.find(p["open"], pos)
                if idx >= 0 and (found is None or idx < found[0]):
                    found = (idx, p)
            if not found:
                break
            idx, p = found
            close_m = p["close"]
            if close_m:
                # block ends at its closing marker (injection markup is not
                # self-nested, so nested openers of the same pair don't matter)
                end = segment.find(close_m, idx + len(p["open"]))
                if end >= 0:
                    end += len(close_m)
                else:
                    end = len(segment)
            else:
                # No closing marker: the block runs from its opening marker
                # until the next injection's opening marker (any pair) or to
                # the end of the current message text.
                end = len(segment)
                for other in pairs:
                    j = segment.find(other["open"], idx + len(p["open"]))
                    if j >= 0 and j < end:
                        end = j
            text = segment[idx:end]
            children = []
            # child blocks: other pairs inside this block's text
            if depth == 0:
                inner = text[len(p["open"]): end - (len(close_m) if close_m and end < len(segment) else 0)]
                scan_children(inner, p["name"], children)
            flat.append({
                "kind": p["name"],
                "text": text,
                "depth": depth,
                "parent": parent,
                "children": children,
            })
            pos = end
            if pos >= len(segment):
                break

    def scan_children(inner, parent_kind, out):
        # Find ALL child blocks of any other pair inside inner,
        # sorted by position of appearance in the text.
        cands = []
        for cp in pairs:
            if cp["name"] == parent_kind:
                continue
            cpos = 0
            while True:
                idx = inner.find(cp["open"], cpos)
                if idx < 0:
                    break
                if cp["close"]:
                    end = inner.find(cp["close"], idx + len(cp["open"]))
                    if end >= 0:
                        end += len(cp["close"])
                    else:
                        end = len(inner)
                else:
                    # no closing marker: until the next injection opener or end
                    end = len(inner)
                    for op in pairs:
                        if op["name"] == cp["name"]:
                            continue
                        j = inner.find(op["open"], idx + len(cp["open"]))
                        if j >= 0 and j < end:
                            end = j
                cands.append((idx, end, cp["name"], inner[idx:end].strip()))
                cpos = end
        cands.sort(key=lambda t: t[0])
        for idx, end, kind, text in cands:
            out.append({
                "kind": kind,
                "text": text,
                "depth": 1,
                "parent": parent_kind,
            })

    scan(rest, 0, None)
    return base, flat


# ── Session inject counting (cached) ────────────────────────────────────────
#
# The sidebar badge counts EVERY recognized injection in the session,
# exactly as the parser displays them per message: each top-level block
# plus its nested children (several injections in one message count as
# several). Sources: the session system prompt, api_content of every
# active message, and tool results (role='tool' content).
# Uses the real extractor (extract_injections) so the badge always matches
# what the user sees inside the session. Results are cached per session
# and invalidated when the session's message set (max id / count) or the
# tag pairs change, so repeated refreshes are cheap.

_inj_count_cache = {}   # session_id -> ((pairs_sig, max_id, msg_count), count)
_sp_inj_cache = {}      # system_prompt_hash -> injection count (immutable per hash)


def _pairs_sig():
    return tuple((p["name"], p["open"]) for p in get_tag_pairs())


def _count_inj_blocks(injections) -> int:
    """Top-level blocks + their children — same formula as the UI countInj()."""
    return sum(1 + len(it.get("children") or []) for it in (injections or []))


def compute_session_injects(con: sqlite3.Connection, session_id: str, pairs) -> int:
    """Count injections across the session (sysprompt + messages) via the parser."""
    if not pairs:
        return 0
    total = 0

    hrow = con.execute(
        "SELECT system_prompt_hash FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    sph = hrow["system_prompt_hash"] if hrow else None
    if sph:
        if sph not in _sp_inj_cache:
            row = con.execute(
                "SELECT prompt FROM system_prompts WHERE hash = ?", (sph,)
            ).fetchone()
            if row and row["prompt"]:
                _, inj = extract_injections(row["prompt"], "")
                _sp_inj_cache[sph] = _count_inj_blocks(inj)
            else:
                _sp_inj_cache[sph] = 0
        total += _sp_inj_cache[sph]

    opens = [p["open"] for p in pairs]
    conds_api = " OR ".join(["instr(api_content, ?) > 0"] * len(opens))
    conds_tool = " OR ".join(["instr(content, ?) > 0"] * len(opens))
    sql = f"""
        SELECT role, api_content, content FROM messages
        WHERE session_id = ? AND active = 1 AND (
          (api_content IS NOT NULL AND ({conds_api}))
          OR (role = 'tool' AND content IS NOT NULL AND ({conds_tool})))
    """
    params = [session_id] + opens + opens
    for r in con.execute(sql, params):
        api = r["api_content"]
        content = decode_content(r["content"])
        content_str = content if isinstance(content, str) else (
            "" if content is None else str(content))
        if isinstance(api, str) and api:
            _, inj = extract_injections(api, content_str)
            total += _count_inj_blocks(inj)
        if r["role"] == "tool" and isinstance(content_str, str) and content_str:
            # tool-memory injections live inside tool results
            _, inj = extract_injections(content_str, "")
            total += _count_inj_blocks(inj)
    return total


def session_inject_counts(con: sqlite3.Connection, session_ids) -> dict:
    """Per-session injection counts, cached until the session changes."""
    pairs = get_tag_pairs()
    sig_base = _pairs_sig()
    counts = {}
    for sid in session_ids:
        row = con.execute(
            "SELECT max(id) AS mx, count(*) AS cnt FROM messages "
            "WHERE session_id = ? AND active = 1", (sid,)
        ).fetchone()
        sig = (sig_base, row["mx"], row["cnt"])
        cached = _inj_count_cache.get(sid)
        if cached and cached[0] == sig:
            counts[sid] = cached[1]
            continue
        c = compute_session_injects(con, sid, pairs) if pairs else 0
        if len(_inj_count_cache) > 5000:
            _inj_count_cache.clear()
        _inj_count_cache[sid] = (sig, c)
        counts[sid] = c
    return counts


# ── API handlers ────────────────────────────────────────────────────────────


def api_sessions(include_id: str = None):
    """Session list sorted by last activity (desc), with inject counts.

    The list holds the most recent `sessions_limit` sessions (config).
    If include_id (the currently open session) falls outside that window,
    it is appended anyway so an open session never disappears on refresh.
    """
    con = db_connect()
    try:
        def row_to_dict(r, counts):
            return {
                "id": r["id"],
                "title": (r["title"] or "")[:80],
                "model": r["model"],
                "started_at": r["started_at"],
                "last_msg": r["last_msg"],
                "last_activity": r["last_msg"] or r["started_at"],
                "cwd": r["cwd"],
                "inject_count": counts.get(r["id"], 0),
            }
        sql = """
            SELECT s.id, s.title, s.model, s.started_at, s.cwd,
                   (SELECT max(m.timestamp) FROM messages m
                    WHERE m.session_id = s.id) AS last_msg
            FROM sessions s
            ORDER BY COALESCE((SELECT max(m.timestamp) FROM messages m
                    WHERE m.session_id = s.id), s.started_at) DESC
            LIMIT ?
        """
        limit = load_sessions_limit()
        rows = con.execute(sql, (limit,)).fetchall()
        counts = session_inject_counts(con, [r["id"] for r in rows])
        result = [row_to_dict(r, counts) for r in rows]
        if include_id and include_id not in {s["id"] for s in result}:
            extra_sql = """
                SELECT s.id, s.title, s.model, s.started_at, s.cwd,
                       (SELECT max(m.timestamp) FROM messages m
                        WHERE m.session_id = s.id) AS last_msg
                FROM sessions s WHERE s.id = ?
            """
            extra = con.execute(extra_sql, (include_id,)).fetchone()
            if extra:
                extra_counts = session_inject_counts(con, [include_id])
                result.append(row_to_dict(extra, extra_counts))
        return {"sessions": result}
    finally:
        con.close()


def api_session_messages(session_id: str):
    """Session messages + system prompt, structured for the UI.

    Injections are parsed for EVERY message role (user, assistant, tool) —
    the parser is universal and does not depend on the agent's prompt layout.
    """
    con = db_connect()
    try:
        sess = con.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not sess:
            return {"error": "session not found", "status": 404}

        rows = con.execute("""
            SELECT id, role, content, api_content, tool_calls, tool_name,
                   tool_call_id, timestamp, reasoning, active, _compressed_summary,
                   display_kind
            FROM messages WHERE session_id = ? AND active = 1
            ORDER BY id
        """, (session_id,)).fetchall()

        messages = []
        for r in rows:
            content = decode_content(r["content"])
            api = r["api_content"]
            ts = r["timestamp"]
            msg = {
                "id": r["id"],
                "role": r["role"],
                "timestamp": ts,
            }
            if r["display_kind"]:
                msg["display_kind"] = r["display_kind"]
            if r["role"] == "assistant" and r["tool_calls"]:
                # Assistant tool call
                try:
                    calls = json.loads(r["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    calls = []
                parsed_calls = []
                for c in calls if isinstance(calls, list) else []:
                    fn = c.get("function", {})
                    args = fn.get("arguments", "")
                    try:
                        args_obj = json.loads(args) if isinstance(args, str) else args
                    except json.JSONDecodeError:
                        args_obj = args
                    parsed_calls.append({
                        "call_id": c.get("id") or c.get("call_id"),
                        "name": fn.get("name", "?"),
                        "arguments": args_obj,
                    })
                msg["tool_calls"] = parsed_calls
                msg["reasoning"] = r["reasoning"]
                msg["content"] = content if isinstance(content, str) else str(content or "")
            elif r["role"] == "tool":
                msg["tool_name"] = r["tool_name"]
                msg["tool_call_id"] = r["tool_call_id"]
                msg["content"] = content if isinstance(content, str) else str(content)
                # Tool-memory injections live INSIDE tool results (content),
                # not in api_content — parse them from there.
                tool_str = msg["content"]
                if isinstance(tool_str, str) and tool_str:
                    base, injections = extract_injections(tool_str, "")
                    if injections:
                        msg["injections"] = injections
                # Unwrap a JSON-string result if it is JSON
                if isinstance(msg["content"], str) and msg["content"].startswith("{"):
                    try:
                        msg["content_json"] = json.loads(msg["content"])
                    except json.JSONDecodeError:
                        pass
            else:
                # user / assistant text / anything else
                msg["content"] = content if isinstance(content, str) else str(content)
                msg["reasoning"] = r["reasoning"]

            # Injections: parsed for EVERY role. api_content is the exact
            # text sent to the LLM; visible content is the clean prefix.
            content_str = msg.get("content")
            if not isinstance(content_str, str):
                content_str = "" if content_str is None else str(content_str)
            if api:
                base, injections = extract_injections(api, content_str)
                if injections:
                    msg["injections"] = injections
            messages.append(msg)

        # System prompt — returned RAW (no section parsing). It is treated
        # as a message-type block in the UI; injections inside it are parsed
        # with the same universal extractor driven by config pairs.
        sys_row = None
        if sess["system_prompt_hash"]:
            sys_row = con.execute(
                "SELECT prompt FROM system_prompts WHERE hash = ?",
                (sess["system_prompt_hash"],),
            ).fetchone()
        system_prompt = None
        if sys_row and sys_row["prompt"]:
            sp = sys_row["prompt"]
            base, sp_injections = extract_injections(sp, "")
            system_prompt = {
                "hash": sess["system_prompt_hash"],
                "length": len(sp),
                "prompt": sp,
                "injections": sp_injections,
            }

        last_msg_row = con.execute(
            "SELECT max(timestamp) AS lm FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        return {
            "session": {
                "id": sess["id"],
                "title": sess["title"],
                "model": sess["model"],
                "started_at": sess["started_at"],
                "last_msg": last_msg_row["lm"] if last_msg_row else None,
                "cwd": sess["cwd"],
                "system_prompt_hash": sess["system_prompt_hash"],
            },
            "system_prompt": system_prompt,
            "messages": messages,
        }
    finally:
        con.close()


def check_db(path_str: str) -> dict:
    """Test readability of a state.db path. Returns {ok, sessions, error}."""
    p = Path(os.path.expanduser(str(path_str or "").strip()))
    if not str(path_str or "").strip():
        return {"ok": False, "error": "path is empty"}
    if not p.exists():
        return {"ok": False, "path": str(p), "error": f"file not found: {p}"}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            n = con.execute("SELECT count(*) FROM sessions").fetchone()[0]
        finally:
            con.close()
        return {"ok": True, "path": str(p), "sessions": n}
    except Exception as e:
        return {"ok": False, "path": str(p), "error": str(e)}


def api_status() -> dict:
    """Server + DB status for the UI (setup wizard / health display)."""
    dbp = get_db_path()
    res = check_db(str(dbp))
    return {
        "ok": True,
        "version": APP_VERSION,
        "config_exists": CONFIG_FILE.exists(),
        "db": {
            "path": str(dbp),
            "exists": bool(res.get("ok")),
            "sessions": res.get("sessions"),
            "error": res.get("error"),
        },
    }


# ── HTTP server ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = f"InjectMonitor/{APP_VERSION.rsplit('.', 1)[0]}"

    def log_message(self, fmt, *args):
        # No verbose stderr logging — one short line to stdout
        print(f"[http] {self.address_string()} {fmt % args}")

    # -- Auth --
    def _authorized(self) -> bool:
        token = get_token()
        got = self.headers.get("X-Auth-Token", "")
        if not got:
            qs = parse_qs(urlparse(self.path).query)
            got = (qs.get("token") or [""])[0]
        return bool(token) and got == token

    # -- Helpers --
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name: str):
        path = (STATIC_DIR / name).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
            self._json({"error": "not found"}, 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }.get(path.suffix, "application/octet-stream")
        body = path.read_bytes()
        if name == "index.html":
            # Real token-file path for the on-screen login instructions
            # (the path only — the token value itself is never served).
            body = body.replace(b"__TOKEN_FILE_PATH__",
                                str(get_token_file()).encode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # No token needed for static files, but data lives behind the API only
        self.end_headers()
        self.wfile.write(body)

    # -- GET --
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        # Any other static file is served freely (favicon, logo, etc.);
        # _static() 404s if missing and refuses paths outside STATIC_DIR.
        if not path.startswith("/api/"):
            cand = path.lstrip("/")
            if (STATIC_DIR / cand).is_file():
                self._static(cand)
                return
        if path == "/api/ping":
            self._json({"ok": True, "version": APP_VERSION})
            return
        # API requires a token
        if not self._authorized():
            self._json({"error": "unauthorized: pass token via X-Auth-Token header or ?token="}, 401)
            return
        if path == "/api/sessions":
            qs = parse_qs(parsed.query)
            include = (qs.get("include") or [""])[0]
            try:
                self._json(api_sessions(include))
            except sqlite3.OperationalError as e:
                self._json({"error": f"database unavailable: {e}"}, 503)
            return
        if path == "/api/status":
            self._json(api_status())
            return
        if path == "/api/config":
            cfg = get_config()
            self._json({
                "port": load_port(),
                "sessions_limit": load_sessions_limit(),
                "db_path": str(cfg.get("db_path") or ""),
                "token_file": str(cfg.get("token_file") or ""),
                "side_width": cfg.get("side_width", 320),
                "tag_pairs": load_tag_pairs(),
                "indent_px": cfg.get("indent_px", DEFAULT_INDENT_PX),
                "expand": _norm_expand(cfg.get("expand")),
                "settings_open": _norm_settings_open(cfg.get("settings_open")),
            })
            return
        if path == "/api/token":
            self._json({"token": get_token()})
            return
        m = re.match(r"^/api/sessions/([^/]+)/messages$", path)
        if m:
            try:
                data = api_session_messages(m.group(1))
            except sqlite3.OperationalError as e:
                self._json({"error": f"database unavailable: {e}"}, 503)
                return
            status = data.pop("status", 200) if isinstance(data, dict) and "status" in data else 200
            self._json(data, status)
            return
        self._json({"error": "not found"}, 404)

    # -- POST --
    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/test-db":
            if not self._authorized():
                self._json({"error": "unauthorized"}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self._json({"error": "invalid json"}, 400)
                return
            if not isinstance(body, dict) or not isinstance(body.get("path"), str):
                self._json({"error": "body must be {\"path\": \"...\"}"}, 400)
                return
            self._json(check_db(body["path"]))
            return
        if parsed.path == "/api/server":
            if not self._authorized():
                self._json({"error": "unauthorized"}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self._json({"error": "invalid json"}, 400)
                return
            action = body.get("action") if isinstance(body, dict) else None
            if action not in ("stop", "restart"):
                self._json({"error": 'action must be "stop" or "restart"'}, 400)
                return
            self._json({"ok": True, "action": action})
            # Give the response a moment to reach the client, then act.
            # stop: shut the HTTP loop down and exit the process.
            # restart: replace the process image with a fresh instance
            # (execv — same interpreter, same script, same port; sockets are
            # close-on-exec, so no port conflict).
            t = threading.Timer(0.4, _server_shutdown_or_restart, args=(action,))
            t.daemon = True
            t.start()
            return
        self._json({"error": "not found"}, 404)

    # -- PUT --
    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            if not self._authorized():
                self._json({"error": "unauthorized"}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self._json({"error": "invalid json"}, 400)
                return
            if not isinstance(body, dict):
                self._json({"error": "body must be an object"}, 400)
                return

            def _int_field(key, lo, hi):
                if key not in body:
                    return None, None
                try:
                    v = int(body.get(key))
                except (TypeError, ValueError):
                    return None, f"{key} must be an integer"
                if not (lo <= v <= hi):
                    return None, f"{key} must be in {lo}..{hi}"
                return v, None

            new_port, err = _int_field("port", 1, 65535)
            if err:
                self._json({"error": err}, 400)
                return
            new_side_width, err = _int_field("side_width", 200, 2000)
            if err:
                self._json({"error": err}, 400)
                return
            new_indent, err = _int_field("indent_px", 0, 120)
            if err:
                self._json({"error": err}, 400)
                return
            new_sessions_limit, err = _int_field("sessions_limit", 1, 500)
            if err:
                self._json({"error": err}, 400)
                return

            # String path fields: non-empty strings
            def _str_field(key):
                if key not in body:
                    return None, None
                v = str(body.get(key) or "").strip()
                if not v or len(v) > 1024:
                    return None, f"{key} must be a non-empty string (max 1024 chars)"
                return v, None

            new_db_path, err = _str_field("db_path")
            if err:
                self._json({"error": err}, 400)
                return
            new_token_file, err = _str_field("token_file")
            if err:
                self._json({"error": err}, 400)
                return

            pairs = body.get("tag_pairs")
            if pairs is not None and not isinstance(pairs, list):
                self._json({"error": "tag_pairs must be a list"}, 400)
                return
            # Optional default-expansion flags for collapsible UI elements
            new_expand = None
            if "expand" in body:
                if not isinstance(body.get("expand"), dict):
                    self._json({"error": "expand must be an object"}, 400)
                    return
                new_expand = {k: bool(v) for k, v in body["expand"].items()
                              if k in DEFAULT_EXPAND}
            # Settings panel blocks: which are expanded (open) — persisted
            new_settings_open = None
            if "settings_open" in body:
                if not isinstance(body.get("settings_open"), list):
                    self._json({"error": "settings_open must be a list"}, 400)
                    return
                new_settings_open = _norm_settings_open(body["settings_open"])
            cleaned = []
            for p in (pairs or []):
                if not isinstance(p, dict):
                    continue
                name = str(p.get("name", "")).strip()
                open_m = str(p.get("open", ""))
                close_m = str(p.get("close", ""))
                if name and open_m:
                    cleaned.append({"name": name, "open": open_m, "close": close_m})

            # Start from the CURRENT FILE content so unknown/custom keys are
            # preserved across saves, then overlay the provided fields.
            cfg = read_config_file()
            out = dict(cfg)
            out["port"] = new_port if new_port is not None else cfg.get("port", DEFAULT_PORT)
            out["side_width"] = (new_side_width if new_side_width is not None
                                 else cfg.get("side_width", 320))
            out["tag_pairs"] = (cleaned if pairs is not None
                                else cfg.get("tag_pairs", BUILTIN_DEFAULTS["tag_pairs"]))
            out["indent_px"] = (new_indent if new_indent is not None
                                else cfg.get("indent_px", DEFAULT_INDENT_PX))
            out["sessions_limit"] = (new_sessions_limit if new_sessions_limit is not None
                                     else cfg.get("sessions_limit", BUILTIN_DEFAULTS["sessions_limit"]))
            out["expand"] = (new_expand if new_expand is not None
                             else cfg.get("expand", DEFAULT_EXPAND))
            out["settings_open"] = (new_settings_open if new_settings_open is not None
                                    else _norm_settings_open(cfg.get("settings_open")))
            out["db_path"] = (new_db_path if new_db_path is not None
                              else cfg.get("db_path", BUILTIN_DEFAULTS["db_path"]))
            out["token_file"] = (new_token_file if new_token_file is not None
                                 else cfg.get("token_file", BUILTIN_DEFAULTS["token_file"]))
            CONFIG_FILE.write_text(
                json.dumps(out, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            invalidate_pairs_cache()
            _inj_count_cache.clear()
            self._json({
                "ok": True,
                "port": out["port"],
                "sessions_limit": out["sessions_limit"],
                "db_path": out["db_path"],
                "token_file": out["token_file"],
                "tag_pairs": load_tag_pairs(),
                "indent_px": out["indent_px"],
                "expand": _norm_expand(out["expand"]),
                "settings_open": _norm_settings_open(out["settings_open"]),
            })
            return
        self._json({"error": "not found"}, 404)


# Live server handle + port (set in main()); used by POST /api/server
HTTP_SERVER = None
RUN_PORT = None


def _server_shutdown_or_restart(action: str):
    """Stop or restart the HTTP server (runs in a timer thread)."""
    global HTTP_SERVER
    try:
        if action == "stop":
            print("Server stop requested via /api/server — shutting down.")
            if HTTP_SERVER is not None:
                HTTP_SERVER.shutdown()
            os._exit(0)
        else:  # restart
            print("Server restart requested via /api/server — execv.")
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__),
                                      "--port", str(RUN_PORT)])
    except Exception as e:  # pragma: no cover
        print(f"ERROR: server {action} failed: {e}")
        os._exit(1)


def main():
    ap = argparse.ArgumentParser(description="Inject Monitor server")
    ap.add_argument("--port", type=int, default=None,
                    help="port override; default: \"port\" from config.json, else %d" % DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    port = args.port if args.port is not None else load_port()

    # First run: create config.json from config.default.json / built-ins

    # Token migration (pre-v0.28 the token lived in ~/.hermes/): if the
    # monitor-folder token does not exist yet but the legacy one does, keep
    # the same token value by copying it — browser sessions stay valid.
    tf = get_token_file()
    legacy = Path(os.path.expanduser("~/.hermes/inject-monitor-token"))
    if not tf.exists() and legacy.exists() and tf != legacy:
        try:
            tf.parent.mkdir(parents=True, exist_ok=True)
            tf.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
            tf.chmod(0o600)
            print(f"Migrated token file: {legacy} -> {tf}")
        except OSError as e:
            print(f"WARN: token migration failed: {e}")
    ensure_default_config()

    # Do NOT exit when the DB is missing — the server starts anyway and the
    # web UI shows the single-window setup wizard so the user can point the
    # monitor at the right database.
    dbp = get_db_path()
    token = get_token()
    print(f"Inject Monitor v{APP_VERSION}")
    print(f"  Config:  {CONFIG_FILE}")
    print(f"  DB:      {dbp}"
          + ("" if dbp.exists() else "   (NOT FOUND — setup wizard opens in the UI)"))
    print(f"  Token:   {get_token_file()}")
    print(f"  Address: http://{args.host}:{port}/?token={token}")
    server = ThreadingHTTPServer((args.host, port), Handler)
    global HTTP_SERVER, RUN_PORT
    HTTP_SERVER = server
    RUN_PORT = port
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
