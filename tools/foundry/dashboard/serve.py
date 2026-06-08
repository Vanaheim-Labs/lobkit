#!/usr/bin/env python3
"""
Foundry Dashboard — Live Server

Serves the Foundry dashboard with live data from wiki vault + Workboard SQLite.
No static baking — data is read fresh on every request.

Usage:
    python3 serve.py [--port 9500] [--manifest PATH] [--db PATH]

Endpoints:
    GET /           → Dashboard HTML (static shell, fetches data client-side)
    GET /api/data   → Live FOUNDRY_DATA JSON
    GET /api/health → Health check
"""

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

# ─────────────────────────────────────────────
#  Data loading (same logic as build.py)
# ─────────────────────────────────────────────


def parse_frontmatter(content):
    if not content.startswith("---"):
        return {}, content
    end = content.find("---", 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    body = content[end + 3:].strip()
    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line and not line.startswith(" ") and not line.startswith("-"):
            key, val = line.split(":", 1)
            val = val.strip().strip('"').strip("'")
            fm[key.strip()] = val
    return fm, body


def load_wiki_pages(vault_path):
    pages = []
    vault = Path(vault_path)
    if not vault.exists():
        return pages
    for md in sorted(vault.rglob("*.md")):
        rel = md.relative_to(vault)
        s = str(rel)
        if s.startswith(".openclaw-wiki") or s.startswith("_"):
            continue
        if rel.name in ("AGENTS.md", "WIKI.md", "inbox.md", "index.md"):
            continue
        try:
            content = md.read_text(errors="replace")
        except Exception:
            continue
        fm, body = parse_frontmatter(content)
        folder = str(rel.parent)
        if folder == ".":
            folder = "root"
        pages.append({
            "path": s,
            "folder": folder,
            "pageType": fm.get("pageType", "unknown"),
            "title": fm.get("title", rel.stem.replace("-", " ").title()),
            "status": fm.get("status", ""),
            "updatedAt": fm.get("updatedAt", ""),
            "entityType": fm.get("entityType", ""),
            "body": body,
        })
    return pages


def load_workboard_full(db_path, board_id):
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute(
        """SELECT id, title, notes, status, priority, agent_id,
                  board_id, created_at, updated_at, started_at, completed_at,
                  source_url, execution_model, execution_status, execution_engine,
                  execution_mode, failure_count, session_key
           FROM workboard_cards
           WHERE board_id = ? AND archived_at IS NULL
           ORDER BY
             CASE status
               WHEN 'running' THEN 1
               WHEN 'blocked' THEN 2
               WHEN 'review' THEN 3
               WHEN 'ready' THEN 4
               WHEN 'todo' THEN 5
               WHEN 'done' THEN 6
             END,
             CASE priority
               WHEN 'urgent' THEN 1
               WHEN 'high' THEN 2
               WHEN 'normal' THEN 3
               WHEN 'low' THEN 4
             END,
             created_at DESC""",
        (board_id,),
    )
    cards = [dict(row) for row in cursor]

    if not cards:
        conn.close()
        return cards

    card_map = {c["id"]: c for c in cards}
    for c in cards:
        c["labels"] = []
        c["events"] = []
        c["attempts"] = []
        c["comments"] = []
        c["proof"] = []
        c["logs"] = []
        c["attachments"] = []
        c["children"] = []

    card_ids = list(card_map.keys())
    ph = ",".join("?" * len(card_ids))

    for row in conn.execute(
        f"SELECT card_id, label FROM workboard_card_labels WHERE card_id IN ({ph}) ORDER BY ordinal",
        card_ids,
    ):
        if row["card_id"] in card_map:
            card_map[row["card_id"]]["labels"].append(row["label"])

    for row in conn.execute(
        f"SELECT card_id, kind, at, from_status, to_status FROM workboard_card_events "
        f"WHERE card_id IN ({ph}) ORDER BY at DESC",
        card_ids,
    ):
        if row["card_id"] in card_map:
            card_map[row["card_id"]]["events"].append({
                "kind": row["kind"], "at": row["at"],
                "from_status": row["from_status"], "to_status": row["to_status"],
            })

    for row in conn.execute(
        f"SELECT card_id, status, started_at, ended_at, engine, mode, model, error "
        f"FROM workboard_card_attempts WHERE card_id IN ({ph}) ORDER BY started_at DESC",
        card_ids,
    ):
        if row["card_id"] in card_map:
            card_map[row["card_id"]]["attempts"].append({
                "status": row["status"], "started_at": row["started_at"],
                "ended_at": row["ended_at"], "engine": row["engine"],
                "mode": row["mode"], "model": row["model"], "error": row["error"],
            })

    for row in conn.execute(
        f"SELECT card_id, body, created_at FROM workboard_card_comments "
        f"WHERE card_id IN ({ph}) ORDER BY created_at ASC",
        card_ids,
    ):
        if row["card_id"] in card_map:
            card_map[row["card_id"]]["comments"].append({
                "body": row["body"], "created_at": row["created_at"],
            })

    for row in conn.execute(
        f"SELECT card_id, status, label, command, note FROM workboard_card_proof "
        f"WHERE card_id IN ({ph}) ORDER BY ordinal",
        card_ids,
    ):
        if row["card_id"] in card_map:
            card_map[row["card_id"]]["proof"].append({
                "status": row["status"], "label": row["label"],
                "command": row["command"], "note": row["note"],
            })

    log_counts = {}
    for row in conn.execute(
        f"SELECT card_id, level, message, created_at FROM workboard_worker_logs "
        f"WHERE card_id IN ({ph}) ORDER BY created_at ASC",
        card_ids,
    ):
        cid = row["card_id"]
        if cid in card_map and log_counts.get(cid, 0) < 100:
            card_map[cid]["logs"].append({
                "level": row["level"], "message": row["message"],
                "created_at": row["created_at"],
            })
            log_counts[cid] = log_counts.get(cid, 0) + 1

    for row in conn.execute(
        f"SELECT card_id, file_name, byte_size, mime_type, note FROM workboard_card_attachments "
        f"WHERE card_id IN ({ph}) ORDER BY ordinal",
        card_ids,
    ):
        if row["card_id"] in card_map:
            card_map[row["card_id"]]["attachments"].append({
                "file_name": row["file_name"], "byte_size": row["byte_size"],
                "mime_type": row["mime_type"], "note": row["note"],
            })

    for row in conn.execute(
        f"SELECT card_id, type, target_card_id, title FROM workboard_card_links "
        f"WHERE card_id IN ({ph}) ORDER BY ordinal",
        card_ids,
    ):
        cid = row["card_id"]
        target = row["target_card_id"]
        if (cid in card_map and row["type"] == "child_of"
                and target and target in card_map):
            parent = card_map[target]
            child = card_map[cid]
            parent["children"].append({
                "id": cid,
                "title": row["title"] or child["title"],
                "status": child["status"],
            })

    conn.close()
    return cards


def build_foundry_data(manifest, db_path):
    data = {
        "workspaces": {},
        "generated_at": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    for ws_id, ws_config in manifest["workspaces"].items():
        vault = os.path.expanduser(ws_config["vault"])
        board = ws_config["board"]
        name = ws_config["name"]

        pages = load_wiki_pages(vault) if os.path.exists(vault) else []
        cards = load_workboard_full(db_path, board)

        data["workspaces"][ws_id] = {
            "id": ws_id,
            "name": name,
            "description": ws_config.get("description", ""),
            "cards": cards,
            "pages": pages,
        }
    return data


# ─────────────────────────────────────────────
#  Simple data cache (avoid re-reading on every request)
# ─────────────────────────────────────────────

class DataCache:
    """Cache data for up to `ttl` seconds, then reload on next request."""

    def __init__(self, manifest, db_path, ttl=5):
        self.manifest = manifest
        self.db_path = db_path
        self.ttl = ttl
        self._data = None
        self._ts = 0
        self._lock = Lock()

    def get(self):
        now = time.monotonic()
        if self._data is not None and (now - self._ts) < self.ttl:
            return self._data
        with self._lock:
            # Double-check after acquiring lock
            if self._data is not None and (time.monotonic() - self._ts) < self.ttl:
                return self._data
            self._data = build_foundry_data(self.manifest, self.db_path)
            self._ts = time.monotonic()
            return self._data

    def invalidate(self):
        """Force next get() to reload from DB."""
        with self._lock:
            self._ts = 0


# ─────────────────────────────────────────────
#  HTTP Handler
# ─────────────────────────────────────────────

# Will be set by main()
_cache: DataCache = None
_html_shell: str = None
_db_path: str = None


import re as _re

VALID_STATUSES = ('todo', 'ready', 'running', 'review', 'blocked', 'done', 'scheduled')


class FoundryHandler(BaseHTTPRequestHandler):
    """Serves the dashboard HTML and live data API."""

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/":
            self._serve_html()
        elif path == "/api/data":
            self._serve_data()
        elif path == "/api/health":
            self._respond_json(200, {"ok": True, "ts": int(time.time() * 1000)})
        else:
            self._respond(404, "text/plain", b"Not found")

    def do_OPTIONS(self):
        """CORS preflight for PATCH/DELETE."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PATCH(self):
        path = urlparse(self.path).path.rstrip("/")
        m = _re.match(r'/api/cards/([^/]+)/status$', path)
        if m:
            card_id = m.group(1)
            body = self._read_body()
            if body is None:
                return
            new_status = body.get('status')
            if new_status not in VALID_STATUSES:
                self._respond_json(400, {"error": f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}"})
                return
            try:
                self._update_card_status(card_id, new_status)
                _cache.invalidate()
                self._respond_json(200, {"ok": True, "id": card_id, "status": new_status})
            except Exception as e:
                self._respond_json(500, {"error": str(e)})
            return
        self._respond(404, "text/plain", b"Not found")

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/")
        m = _re.match(r'/api/cards/([^/]+)$', path)
        if m:
            card_id = m.group(1)
            try:
                self._archive_card(card_id)
                _cache.invalidate()
                self._respond_json(200, {"ok": True, "id": card_id, "archived": True})
            except Exception as e:
                self._respond_json(500, {"error": str(e)})
            return
        self._respond(404, "text/plain", b"Not found")

    def _read_body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length)
            return json.loads(raw) if raw else {}
        except Exception as e:
            self._respond_json(400, {"error": f"Invalid JSON: {e}"})
            return None

    def _update_card_status(self, card_id, new_status):
        import uuid
        now_ms = int(time.time() * 1000)
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM workboard_cards WHERE id = ?", (card_id,)).fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Card {card_id} not found")
        old_status = row["status"]
        conn.execute(
            "UPDATE workboard_cards SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now_ms, card_id),
        )
        # Get next ordinal for this card's events
        max_ord = conn.execute(
            "SELECT COALESCE(MAX(ordinal), -1) FROM workboard_card_events WHERE card_id = ?",
            (card_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO workboard_card_events (id, card_id, ordinal, kind, at, from_status, to_status) "
            "VALUES (?, ?, ?, 'status_change', ?, ?, ?)",
            (str(uuid.uuid4()), card_id, max_ord + 1, now_ms, old_status, new_status),
        )
        conn.commit()
        conn.close()

    def _archive_card(self, card_id):
        now_ms = int(time.time() * 1000)
        conn = sqlite3.connect(_db_path)
        result = conn.execute(
            "UPDATE workboard_cards SET archived_at = ?, updated_at = ? WHERE id = ? AND archived_at IS NULL",
            (now_ms, now_ms, card_id),
        )
        if result.rowcount == 0:
            conn.close()
            raise ValueError(f"Card {card_id} not found or already archived")
        conn.commit()
        conn.close()

    def _serve_html(self):
        body = _html_shell.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _serve_data(self):
        data = _cache.get()
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _respond_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quieter logging — just method + path + status
        pass


# ─────────────────────────────────────────────
#  HTML shell (modified from build.py template)
# ─────────────────────────────────────────────

def build_html_shell(manifest):
    """Build the HTML shell with workspace switcher pre-rendered
    but data loaded via fetch('/api/data')."""

    import html as html_mod

    ws_options = []
    for i, (ws_id, ws) in enumerate(manifest["workspaces"].items()):
        active = " active" if i == 0 else ""
        name = html_mod.escape(ws["name"])
        wid = html_mod.escape(ws_id)
        ws_options.append(
            f'<button class="ws-btn{active}" data-ws="{wid}" '
            f'onclick="switchWs(\'{wid}\', this)">{name}</button>'
        )
    ws_options_html = "\n  ".join(ws_options)

    # Read the template from build.py — extract and patch it
    return _make_live_html(ws_options_html)


def _make_live_html(ws_options_html):
    """Return the full HTML with fetch-based data loading."""

    # We inline the entire UI from build.py's HTML_TEMPLATE but replace:
    # 1. window.FOUNDRY_DATA = __FOUNDRY_DATA__ → fetched via API
    # 2. initApp() → fetchAndInit()
    # 3. Footer shows "Live" instead of build timestamp
    # 4. Add auto-refresh toggle

    # Import the template from build.py
    import importlib.util
    build_py = Path(__file__).parent / "build.py"
    spec = importlib.util.spec_from_file_location("build", build_py)
    build_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_mod)

    template = build_mod.HTML_TEMPLATE

    # Patch 1: Replace embedded data with fetch
    old_data_line = "window.FOUNDRY_DATA = __FOUNDRY_DATA__;"
    new_data_block = """window.FOUNDRY_DATA = null;
let _autoRefreshInterval = null;
let _autoRefresh = true;

async function fetchData() {
  try {
    const resp = await fetch('/api/data');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    window.FOUNDRY_DATA = await resp.json();
    return true;
  } catch (e) {
    console.error('Failed to load data:', e);
    document.getElementById('main-content').innerHTML =
      '<div class="empty-state"><div class="empty-icon">⚠️</div>' +
      '<p>Failed to load data. Is the server running?</p>' +
      '<p style="color:var(--text-muted);font-size:12px">' + e.message + '</p></div>';
    return false;
  }
}

async function fetchAndInit() {
  if (await fetchData()) {
    initApp();
    updateTimestamp();
  }
}

async function refreshData() {
  if (await fetchData()) {
    // Preserve current workspace and tab selection
    renderWorkspace();
    updateTimestamp();
  }
}

function updateTimestamp() {
  const ts = window.FOUNDRY_DATA ? window.FOUNDRY_DATA.generated_at : null;
  const el = document.getElementById('footer-note');
  if (ts && el) {
    const d = new Date(ts);
    const fmt = d.toLocaleTimeString('en-AU', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
    const autoLabel = _autoRefresh ? '· auto-refresh on' : '· auto-refresh off';
    el.innerHTML = '🟢 Live · Last loaded ' + fmt + ' ' + autoLabel +
      ' · <button onclick="toggleAutoRefresh()" style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:11px;text-decoration:underline">' +
      (_autoRefresh ? 'pause' : 'resume') + '</button>' +
      ' · <button onclick="refreshData()" style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:11px;text-decoration:underline">refresh now</button>';
  }
}

function toggleAutoRefresh() {
  _autoRefresh = !_autoRefresh;
  if (_autoRefresh) {
    _autoRefreshInterval = setInterval(refreshData, 15000);
  } else {
    clearInterval(_autoRefreshInterval);
    _autoRefreshInterval = null;
  }
  updateTimestamp();
}

// Start auto-refresh (every 15s)
_autoRefreshInterval = setInterval(refreshData, 15000);"""

    template = template.replace(old_data_line, new_data_block)

    # Patch 2: Replace initApp() call at the end with fetchAndInit()
    template = template.replace(
        "// ── Boot ───────────────────────────────────────────────────\ninitApp();",
        "// ── Boot ───────────────────────────────────────────────────\nfetchAndInit();"
    )

    # Patch 3: Replace static placeholders
    template = template.replace("__WS_OPTIONS__", ws_options_html)
    template = template.replace(
        "Generated __BUILD_TS__ · Foundry v3",
        "🟢 Loading… · Foundry v3"
    )

    return template


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

def main():
    global _cache, _html_shell, _db_path

    parser = argparse.ArgumentParser(description="Foundry Dashboard — Live Server")
    parser.add_argument("--port", type=int, default=9500)
    parser.add_argument(
        "--manifest",
        default=os.path.expanduser(
            "~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json"
        ),
    )
    parser.add_argument(
        "--db",
        default=os.path.expanduser("~/.openclaw/plugins/workboard/workboard.sqlite"),
    )
    parser.add_argument("--ttl", type=int, default=5, help="Data cache TTL in seconds")
    args = parser.parse_args()

    # Load manifest
    with open(args.manifest) as f:
        manifest = json.load(f)

    # Set up cache and DB path for write operations
    _db_path = args.db
    _cache = DataCache(manifest, args.db, ttl=args.ttl)

    # Build HTML shell
    _html_shell = build_html_shell(manifest)

    # Pre-warm cache
    _cache.get()

    server = HTTPServer(("0.0.0.0", args.port), FoundryHandler)
    print(f"⚒️  Foundry Dashboard — Live Server")
    print(f"   http://localhost:{args.port}")
    print(f"   Manifest: {args.manifest}")
    print(f"   Workboard DB: {args.db}")
    print(f"   Cache TTL: {args.ttl}s")
    print(f"   Auto-refresh: 15s (client-side)")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
