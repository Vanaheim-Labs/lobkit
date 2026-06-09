#!/usr/bin/env python3
"""
Foundry Dashboard — Rich Static Site Generator v4

Reads the wiki vault + workboard SQLite and generates a self-contained
HTML dashboard with a Workboard-quality UI.

Features:
- Right-side slide-out detail panel (440px / 520px on wide screens)
- Full card data: events timeline, execution attempts, worker logs,
  proof, comments, attachments, sub-cards
- Client-side search and multi-filter (status, priority, agent, text)
- Pulsing running cards, colored priority/status/agent badges
- Wiki knowledge slide-out panel with search, folder filters, decision log
- Sources tab with search, excerpts, and stats
- Multi-workspace support via manifest.json
- Keyboard shortcuts overlay (?), smart timestamps (Today/Yesterday)
- All data embedded as window.FOUNDRY_DATA JSON

Usage:
    python3 build.py [--manifest PATH] [--db PATH] [--out PATH]
"""

import argparse
import html as html_mod
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ─────────────────────────────────────────────
#  Data loading
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
            "body": body[:32000],
            "bodyTruncated": len(body) > 32000,
        })
    return pages


def load_workboard_full(db_path, board_id):
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
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


def load_manifest(path):
    with open(path) as f:
        return json.load(f)


def build_foundry_data(manifest, db_path):
    data = {
        "workspaces": {},
        "generated_at": int(datetime.now().timestamp() * 1000),
    }
    for ws_id, ws_config in manifest["workspaces"].items():
        vault = os.path.expanduser(ws_config["vault"])
        board = ws_config["board"]
        name = ws_config["name"]

        print(f"[{name}] Loading wiki vault: {vault}")
        pages = load_wiki_pages(vault) if os.path.exists(vault) else []
        print(f"  -> {len(pages)} pages")

        print(f"[{name}] Loading workboard: board={board}")
        cards = load_workboard_full(db_path, board)
        print(f"  -> {len(cards)} cards")

        data["workspaces"][ws_id] = {
            "id": ws_id,
            "name": name,
            "description": ws_config.get("description", ""),
            "cards": cards,
            "pages": pages,
        }
    return data


# ─────────────────────────────────────────────
#  HTML Template (token-replacement, no f-string)
# ─────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Foundry Dashboard</title>
<style>
/* Light theme (default) */
:root {
  --bg: #ffffff;
  --surface: #f6f8fa;
  --surface2: #eaeef2;
  --surface3: #d0d7de;
  --border: #d0d7de;
  --border-muted: #e1e4e8;
  --text: #1f2328;
  --text-muted: #656d76;
  --text-subtle: #8b949e;
  --accent: #0969da;
  --green: #1a7f37;
  --red: #cf222e;
  --orange: #9a6700;
  --purple: #8250df;
  --panel-width: 580px;
  --pill-on-accent: #fff;
  --panel-bg: #ffffff;
  --panel-shadow: 0 0 0 1px rgba(31,35,40,0.04), 0 8px 24px rgba(31,35,40,0.12);
  --card-shadow: 0 1px 3px rgba(31,35,40,0.04);
  --overlay-bg: rgba(0,0,0,0.3);
}
/* Dark theme */
[data-theme="dark"] {
  --bg: #0d1117;
  --surface: #161b22;
  --surface2: #21262d;
  --surface3: #2d333b;
  --border: #30363d;
  --border-muted: #21262d;
  --text: #e6edf3;
  --text-muted: #8b949e;
  --text-subtle: #484f58;
  --accent: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --orange: #d29922;
  --purple: #bc8cff;
  --pill-on-accent: #000;
  --panel-bg: #161b22;
  --panel-shadow: 0 0 0 1px rgba(255,255,255,0.05), 0 8px 24px rgba(0,0,0,0.4);
  --card-shadow: none;
  --overlay-bg: rgba(0,0,0,0.7);
}
@media (min-width: 1400px) {
  :root { --panel-width: 700px; }
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { font-size: 14px; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
button { cursor: pointer; font-family: inherit; }

/* Header */
.header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  height: 52px;
  position: sticky;
  top: 0;
  z-index: 50;
}
.header-logo {
  font-size: 18px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}
.header-tagline {
  color: var(--text-muted);
  font-size: 12px;
  flex: 1;
}
.theme-toggle {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 15px;
  line-height: 1;
  color: var(--text);
  transition: background 0.15s, border-color 0.15s;
  flex-shrink: 0;
}
.theme-toggle:hover { background: var(--surface3); border-color: var(--text-muted); }

/* Workspace Switcher */
.ws-switcher {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 8px 24px;
  display: flex;
  gap: 6px;
  overflow-x: auto;
}
.ws-btn {
  padding: 5px 16px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s;
  white-space: nowrap;
}
.ws-btn:hover { color: var(--text); border-color: var(--text-muted); }
.ws-btn.active { background: var(--accent); color: var(--pill-on-accent); border-color: var(--accent); font-weight: 600; }

/* Inner Tabs */
.inner-tabs {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  display: flex;
}
.itab {
  padding: 10px 18px;
  color: var(--text-muted);
  border-bottom: 2px solid transparent;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  gap: 6px;
}
.itab:hover { color: var(--text); }
.itab.active { color: var(--accent); border-bottom-color: var(--accent); }
.badge-count {
  background: var(--surface2);
  color: var(--text-muted);
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}
.itab.active .badge-count { background: rgba(88,166,255,0.15); color: var(--accent); }

/* Main Content */
.main-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px 24px;
}
.main-content.kanban-mode {
  max-width: none;
  padding: 12px 16px;
}
.main-content.kanban-mode .stats-grid { display: none; }

/* Stats */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 20px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  transition: border-color 0.2s;
}
.stat-card.has-value { border-left: 3px solid var(--accent); }
.stat-card.has-value.c-green { border-left-color: var(--green); border-color: var(--border); }
.stat-card.has-value.c-red { border-left-color: var(--red); border-color: var(--border); }
.stat-card.has-value.c-orange { border-left-color: var(--orange); border-color: var(--border); }
.stat-value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 4px;
}
.stat-value.c-accent { color: var(--accent); }
.stat-value.c-green { color: var(--green); }
.stat-value.c-red { color: var(--red); }
.stat-value.c-orange { color: var(--orange); }
.stat-label { color: var(--text-muted); font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }

/* Controls */
.controls-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.search-wrap { position: relative; flex: 1; min-width: 180px; }
.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  pointer-events: none;
  font-size: 13px;
}
.search-input {
  width: 100%;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 10px 7px 32px;
  color: var(--text);
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus { border-color: var(--accent); background: var(--surface); }
.search-input::placeholder { color: var(--text-muted); }
.filter-select {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 10px;
  color: var(--text);
  font-size: 13px;
  outline: none;
  cursor: pointer;
  transition: border-color 0.15s;
}
.filter-select:focus { border-color: var(--accent); }
.filter-select { -webkit-appearance: none; -moz-appearance: none; appearance: none; padding-right: 30px; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 5l3 3 3-3' stroke='%238b949e' fill='none' stroke-width='1.5'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 10px center; }
.filter-select option { background: var(--surface); color: var(--text); }

/* Status filter pills */
.status-filters {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.sf-btn {
  padding: 3px 11px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  transition: all 0.12s;
}
.sf-btn:hover { border-color: var(--text-muted); color: var(--text); }
.sf-btn.active { background: var(--surface2); color: var(--text); border-color: var(--text-muted); }
.sf-btn[data-s="running"].active { background: rgba(88,166,255,0.15); border-color: var(--accent); color: var(--accent); }
.sf-btn[data-s="blocked"].active { background: rgba(248,81,73,0.15); border-color: var(--red); color: var(--red); }
.sf-btn[data-s="done"].active { background: rgba(63,185,80,0.12); border-color: var(--green); color: var(--green); }
.sf-btn[data-s="ready"].active { background: rgba(63,185,80,0.1); border-color: var(--green); color: #7ee787; }
.sf-btn[data-s="review"].active { background: rgba(210,153,34,0.15); border-color: var(--orange); color: var(--orange); }
.sf-btn[data-s="todo"].active { background: rgba(139,148,158,0.12); border-color: var(--text-muted); color: var(--text-muted); }
.sf-btn[data-s="scheduled"].active { background: rgba(188,140,255,0.12); border-color: var(--purple); color: var(--purple); }

/* Folder filter pills (knowledge tab) */
.folder-filters {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.ff-btn {
  padding: 3px 11px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  transition: all 0.12s;
}
.ff-btn:hover { border-color: var(--text-muted); color: var(--text); }
.ff-btn.active { background: var(--surface2); color: var(--text); border-color: var(--text-muted); }
.ff-btn.decision-btn.active {
  background: rgba(88,166,255,0.15);
  border-color: var(--accent);
  color: var(--accent);
}

/* Card list (legacy) */
.card-list { display: flex; flex-direction: column; gap: 8px; }
.card-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 13px 15px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
  border-left: 3px solid var(--border);
}
.card-item { box-shadow: var(--card-shadow); }
.card-item:hover { border-color: var(--accent); border-left-color: var(--accent); box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
.card-item.s-running { border-left-color: var(--accent); animation: pulseLeft 2.2s ease-in-out infinite; }
.card-item.s-blocked { border-left-color: var(--red); }
.card-item.s-done { border-left-color: var(--green); opacity: 0.72; }
.card-item.s-ready { border-left-color: var(--green); }
.card-item.s-review { border-left-color: var(--orange); }
.card-item.s-todo { border-left-color: var(--text-subtle); }
.card-item.s-scheduled { border-left-color: var(--purple); }
@keyframes pulseLeft {
  0%, 100% { border-left-color: var(--accent); }
  50% { border-left-color: #79c0ff; }
}
.card-row1 { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; margin-bottom: 6px; }
.card-title { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 4px; line-height: 1.35; }
.card-notes { font-size: 12px; color: var(--text-muted); line-height: 1.45; margin-bottom: 6px; }
.card-row2 { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.card-id { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 11px; color: var(--text-subtle); }
.card-date { font-size: 11px; color: var(--text-muted); margin-left: auto; }

/* Kanban Board */
.kanban-board {
  display: flex;
  gap: 10px;
  padding-bottom: 12px;
  min-height: 400px;
  align-items: flex-start;
  height: calc(100vh - 280px);
}
.kanban-col {
  flex: 1 1 0;
  min-width: 200px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.kanban-col-header {
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  background: var(--surface2);
  border-radius: 10px 10px 0 0;
}
.kanban-col-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.kanban-col-dot.d-running { background: var(--accent); }
.kanban-col-dot.d-blocked { background: var(--red); }
.kanban-col-dot.d-review { background: var(--orange); }
.kanban-col-dot.d-ready { background: var(--green); }
.kanban-col-dot.d-todo { background: var(--text-muted); }
.kanban-col-dot.d-done { background: var(--green); opacity: 0.6; }
.kanban-col-dot.d-scheduled { background: var(--purple); }
.kanban-col-name {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}
.kanban-col-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-subtle);
  background: var(--surface3);
  padding: 1px 7px;
  border-radius: 10px;
  margin-left: auto;
}
.kanban-col-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kanban-col-body:empty::after {
  content: 'No cards';
  display: block;
  text-align: center;
  color: var(--text-subtle);
  font-size: 12px;
  padding: 24px 8px;
}
.kanban-card {
  background: var(--bg);
  border: 1px solid var(--border-muted);
  border-radius: 6px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.1s;
  border-left: 3px solid var(--border);
}
.kanban-card:hover {
  border-color: var(--accent);
  border-left-color: var(--accent);
  box-shadow: 0 2px 8px rgba(0,0,0,0.12);
  transform: translateY(-1px);
}
.kanban-card.s-running { border-left-color: var(--accent); animation: pulseLeft 2.2s ease-in-out infinite; }
.kanban-card.s-blocked { border-left-color: var(--red); }
.kanban-card.s-done { border-left-color: var(--green); opacity: 0.7; }
.kanban-card.s-ready { border-left-color: var(--green); }
.kanban-card.s-review { border-left-color: var(--orange); }
.kanban-card.s-todo { border-left-color: var(--text-subtle); }
.kanban-card.s-scheduled { border-left-color: var(--purple); }
.kanban-card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.35;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.kanban-card-pills {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 5px;
}
.kanban-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  margin-top: 4px;
}
.kanban-card-id {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 10px;
  color: var(--text-subtle);
}
.kanban-card-date {
  font-size: 10px;
  color: var(--text-subtle);
}

/* Cost badge on kanban cards */
.kanban-card-cost {
  font-size: 10px;
  color: var(--green);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.kanban-card-cost .cost-tokens {
  color: var(--text-subtle);
  font-weight: 400;
  margin-left: 2px;
}

/* Cost breakdown in card detail panel */
.cost-breakdown {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.cost-stat {
  background: var(--surface);
  border-radius: 6px;
  padding: 8px 10px;
}
.cost-stat-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.cost-stat-value.cost-primary {
  color: var(--green);
}
.cost-stat-label {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.cost-bar {
  display: flex;
  height: 6px;
  border-radius: 3px;
  overflow: hidden;
  background: var(--surface2);
  margin-top: 10px;
}
.cost-bar-seg {
  height: 100%;
  transition: width 0.3s ease;
}
.cost-bar-seg.cb-input { background: var(--accent); }
.cost-bar-seg.cb-output { background: var(--green); }
.cost-bar-seg.cb-cache-read { background: var(--orange); opacity: 0.6; }
.cost-bar-seg.cb-cache-write { background: var(--purple); opacity: 0.6; }
.cost-bar-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 6px;
  font-size: 10px;
  color: var(--text-muted);
}
.cost-bar-legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-right: 3px;
  vertical-align: middle;
}

/* Drag & Drop */
.kanban-card[draggable="true"] { cursor: grab; }
.kanban-card[draggable="true"]:active { cursor: grabbing; }
.kanban-card.dragging {
  opacity: 0.4;
  transform: rotate(2deg);
  box-shadow: 0 4px 16px rgba(0,0,0,0.2);
}
.kanban-col-body.drag-over {
  background: rgba(88,166,255,0.06);
  border: 2px dashed var(--accent);
  border-radius: 6px;
}
.kanban-col.drag-target .kanban-col-header {
  background: rgba(88,166,255,0.12);
}

/* Delete button */
.kanban-card-delete {
  position: absolute;
  top: 6px;
  right: 6px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 5px;
  font-size: 12px;
  line-height: 1;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s, color 0.15s, background 0.15s, border-color 0.15s;
  z-index: 5;
}
.kanban-card:hover .kanban-card-delete { opacity: 1; }
.kanban-card-delete:hover {
  color: var(--red);
  background: rgba(248,81,73,0.1);
  border-color: rgba(248,81,73,0.3);
}
.kanban-card { position: relative; }

/* Dispatch button */
.dispatch-btn {
  background: var(--accent);
  color: var(--pill-on-accent);
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  font-weight: 500;
  white-space: nowrap;
  transition: opacity 0.15s;
}
.dispatch-btn:hover { opacity: 0.9; }
.dispatch-btn:disabled { opacity: 0.5; cursor: not-allowed; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
.dispatch-btn.loading { animation: pulse 1s ease-in-out infinite; }

/* Per-card play button */
.kanban-card-play {
  position: absolute;
  top: 6px;
  right: 26px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.15s;
  color: var(--accent);
  padding: 2px 4px;
  z-index: 5;
}
.kanban-card:hover .kanban-card-play { opacity: 0.7; }
.kanban-card-play:hover { opacity: 1 !important; }
.kanban-card-play:disabled { opacity: 0.3; cursor: not-allowed; }

/* Toast notifications */
.toast-container {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 400;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 13px;
  color: var(--text);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  animation: toastIn 0.25s ease-out;
  max-width: 380px;
}
.toast.t-success { border-left: 3px solid var(--green); }
.toast.t-error { border-left: 3px solid var(--red); }
.toast.t-info { border-left: 3px solid var(--accent); }
@keyframes toastIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }

/* Confirm modal */
.confirm-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: var(--overlay-bg);
  z-index: 300;
  backdrop-filter: blur(3px);
  align-items: center;
  justify-content: center;
}
.confirm-overlay.open { display: flex; }
.confirm-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  max-width: 400px;
  width: 90%;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
.confirm-title { font-size: 16px; font-weight: 700; margin-bottom: 8px; color: var(--text); }
.confirm-msg { font-size: 13px; color: var(--text-muted); margin-bottom: 18px; line-height: 1.5; }
.confirm-actions { display: flex; gap: 8px; justify-content: flex-end; }
.confirm-btn {
  padding: 7px 16px;
  border-radius: 6px;
  border: 1px solid var(--border);
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s;
}
.confirm-cancel {
  background: var(--surface2);
  color: var(--text);
}
.confirm-cancel:hover { background: var(--surface3); }
.confirm-danger {
  background: var(--red);
  color: #fff;
  border-color: var(--red);
}
.confirm-danger:hover { opacity: 0.85; }

/* Pills / Badges */
.pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
}
.ps-running { background: rgba(88,166,255,0.15); color: var(--accent); border: 1px solid rgba(88,166,255,0.3); }
.ps-blocked { background: rgba(248,81,73,0.15); color: var(--red); border: 1px solid rgba(248,81,73,0.3); }
.ps-done { background: rgba(63,185,80,0.12); color: var(--green); border: 1px solid rgba(63,185,80,0.25); }
.ps-ready { background: rgba(63,185,80,0.1); color: #7ee787; border: 1px solid rgba(63,185,80,0.2); }
.ps-review { background: rgba(210,153,34,0.15); color: var(--orange); border: 1px solid rgba(210,153,34,0.3); }
.ps-todo { background: var(--surface2); color: var(--text-muted); border: 1px solid var(--border); }
.ps-scheduled { background: rgba(188,140,255,0.12); color: var(--purple); border: 1px solid rgba(188,140,255,0.25); }
.pp-urgent { background: rgba(248,81,73,0.2); color: #ff7b72; border: 1px solid rgba(248,81,73,0.35); }
.pp-high { background: rgba(210,153,34,0.18); color: var(--orange); border: 1px solid rgba(210,153,34,0.3); }
.pp-normal { background: var(--surface2); color: var(--text-muted); border: 1px solid var(--border); }
.pp-low { background: rgba(63,185,80,0.1); color: #7ee787; border: 1px solid rgba(63,185,80,0.2); }
.pl-label { background: rgba(188,140,255,0.12); color: var(--purple); border: 1px solid rgba(188,140,255,0.25); }
.pl-source { background: rgba(88,166,255,0.08); color: #79c0ff; border: 1px solid rgba(88,166,255,0.2); }
.pl-source:hover { background: rgba(88,166,255,0.15); cursor: pointer; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; margin-right: 3px; }
.badge-entity { background: #1f3a5f; color: var(--accent); }
.badge-source { background: #2a1f3f; color: var(--purple); }
.badge-synthesis { background: #1f3f2a; color: var(--green); }
.badge-concept { background: #3f2a1f; color: var(--orange); }
.badge-unknown { background: var(--surface2); color: var(--text-muted); }
.badge-report { background: #2a2f1f; color: #a8b56f; }
.badge-muted { background: var(--surface2); color: var(--text-muted); }

/* Empty state */
.empty-state { text-align: center; padding: 48px 24px; color: var(--text-muted); }
.empty-icon { font-size: 32px; margin-bottom: 12px; }
.empty-actions { margin-top: 14px; display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
.empty-action-btn {
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.12s;
}
.empty-action-btn:hover { border-color: var(--accent); color: var(--accent); }

/* Slide-out panel */
.panel-backdrop {
  display: none;
  position: fixed;
  inset: 0;
  background: var(--overlay-bg);
  z-index: 200;
  backdrop-filter: blur(2px);
}
.panel-backdrop.open { display: block; }
.detail-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: var(--panel-width);
  max-width: 100vw;
  background: var(--surface);
  border-left: 1px solid var(--border);
  z-index: 201;
  transform: translateX(100%);
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.detail-panel.open { transform: translateX(0); }
.panel-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 18px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  background: var(--surface2);
}
.panel-hdr-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.panel-close {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 17px;
  line-height: 1;
  padding: 4px 8px;
  border-radius: 4px;
  transition: color 0.1s, background 0.1s;
}
.panel-close:hover { color: var(--text); background: var(--surface3); }
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 20px 32px;
  scroll-behavior: smooth;
}

/* Panel content */
.panel-title {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.35;
  margin-bottom: 12px;
  color: var(--text);
}
.panel-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 14px;
  padding: 11px 12px;
  background: var(--surface2);
  border-radius: 6px;
  border: 1px solid var(--border-muted);
}
.pm-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-muted);
  margin-bottom: 3px;
}
.pm-value { font-size: 12px; color: var(--text); }
.panel-section {
  margin-top: 16px;
  padding-top: 13px;
  border-top: 1px solid var(--border);
}
.panel-sec-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin-bottom: 10px;
}
.panel-labels { display: flex; gap: 5px; flex-wrap: wrap; }

/* Notes: Objective / DoD / Source-ref highlighted sections */
.notes-objective {
  background: rgba(63,185,80,0.06);
  border: 1px solid rgba(63,185,80,0.2);
  border-left: 3px solid var(--green);
  border-radius: 6px;
  padding: 10px 13px;
  margin-bottom: 10px;
}
.notes-dod {
  background: rgba(88,166,255,0.06);
  border: 1px solid rgba(88,166,255,0.2);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 10px 13px;
  margin-bottom: 10px;
}
.completion-summary {
  background: rgba(63,185,80,0.06);
  border: 1px solid rgba(63,185,80,0.2);
  border-left: 3px solid var(--green);
  border-radius: 6px;
  padding: 10px 13px;
  margin-bottom: 10px;
}
.notes-section-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-muted);
  margin-bottom: 5px;
}
.notes-section-body {
  font-size: 13px;
  color: var(--text);
  line-height: 1.55;
}
.notes-source-ref {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 10px;
}

/* Markdown body */
.md-body { font-size: 13px; line-height: 1.65; color: var(--text); }
.md-body h2 { font-size: 15px; font-weight: 700; margin: 14px 0 6px; color: var(--accent); }
.md-body h3 { font-size: 13px; font-weight: 600; margin: 10px 0 4px; color: #79c0ff; }
.md-body p { margin-bottom: 8px; }
.md-body ul, .md-body ol { margin-left: 18px; margin-bottom: 8px; }
.md-body li { margin-bottom: 3px; }
.md-body code {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 5px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
}
.md-body pre {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  margin-bottom: 8px;
}
.md-body pre code { border: none; padding: 0; background: none; }
.md-body strong { font-weight: 700; }
.md-body em { font-style: italic; }
.md-body blockquote { border-left: 3px solid var(--border); padding-left: 10px; color: var(--text-muted); margin-bottom: 8px; }
.md-body hr { border: none; border-top: 1px solid var(--border); margin: 10px 0; }
.md-body a { color: var(--accent); }
.md-table-wrap { overflow-x: auto; margin-bottom: 10px; border-radius: 6px; border: 1px solid var(--border); }
.md-table { width: 100%; border-collapse: collapse; font-size: 12px; line-height: 1.5; }
.md-table th { background: var(--surface2); font-weight: 600; text-align: left; padding: 7px 10px; border-bottom: 2px solid var(--border); white-space: nowrap; }
.md-table td { padding: 6px 10px; border-bottom: 1px solid var(--border-muted); vertical-align: top; }
.md-table tbody tr:last-child td { border-bottom: none; }
.md-table tbody tr:hover { background: var(--surface2); }

/* Timeline */
.timeline { display: flex; flex-direction: column; gap: 9px; }
.tl-item { display: flex; gap: 10px; align-items: flex-start; }
.tl-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--border);
  margin-top: 4px;
  flex-shrink: 0;
}
.tl-dot.dk-created { background: var(--text-muted); }
.tl-dot.dk-claimed, .tl-dot.dk-claim_acquired { background: var(--accent); }
.tl-dot.dk-completed, .tl-dot.dk-done { background: var(--green); }
.tl-dot.dk-failed, .tl-dot.dk-blocked { background: var(--red); }
.tl-dot.dk-status_changed, .tl-dot.dk-status_change { background: var(--orange); }
.tl-dot.dk-started { background: var(--accent); }
.tl-body { flex: 1; }
.tl-kind { font-size: 12px; font-weight: 600; color: var(--text); text-transform: capitalize; }
.tl-sub { font-size: 11px; color: var(--text-muted); margin-top: 1px; }
.tl-time { font-size: 11px; color: var(--text-subtle); white-space: nowrap; flex-shrink: 0; }

/* Attempts */
.attempt-item {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 6px;
  font-size: 12px;
}
.attempt-hdr { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.attempt-detail { color: var(--text-muted); line-height: 1.5; }
.attempt-error {
  margin-top: 6px;
  background: rgba(248,81,73,0.08);
  border: 1px solid rgba(248,81,73,0.2);
  border-radius: 4px;
  padding: 6px 8px;
  color: #ff7b72;
  font-size: 11px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Worker logs */
.log-list {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  max-height: 200px;
  overflow-y: auto;
}
.log-item {
  display: flex;
  gap: 8px;
  padding: 2px 0;
  font-size: 11px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  border-bottom: 1px solid var(--border-muted);
}
.log-item:last-child { border-bottom: none; }
.log-time { color: var(--text-subtle); flex-shrink: 0; }
.ll-info { color: var(--text); }
.ll-warn { color: var(--orange); }
.ll-error { color: var(--red); }

/* Proof */
.proof-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border-muted);
  font-size: 12px;
}
.proof-item:last-child { border-bottom: none; }
.proof-ico { flex-shrink: 0; font-size: 14px; }
.proof-body { flex: 1; }
.proof-label { font-weight: 600; color: var(--text); margin-bottom: 2px; }
.proof-cmd {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
  color: var(--text-muted);
  background: var(--surface2);
  padding: 2px 6px;
  border-radius: 3px;
  margin-top: 2px;
  display: inline-block;
}
.proof-note { color: var(--text-muted); margin-top: 2px; }

/* Comments */
.comment-item {
  padding: 9px 11px;
  background: var(--surface2);
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 12px;
  line-height: 1.5;
}
.comment-time { color: var(--text-subtle); font-size: 10px; margin-top: 5px; }

/* Attachments */
.attach-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border-muted);
  font-size: 12px;
}
.attach-item:last-child { border-bottom: none; }
.attach-icon { font-size: 16px; flex-shrink: 0; }
.attach-name { font-weight: 500; color: var(--text); }
.attach-meta { color: var(--text-muted); font-size: 11px; }
.attach-note { color: var(--text-muted); font-size: 11px; font-style: italic; }

/* Sub-cards */
.subcard-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.1s;
  font-size: 12px;
}
.subcard-item:hover { background: var(--surface2); }

/* Knowledge Grid */
.knowledge-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 10px;
}
.wiki-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 13px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.wiki-card:hover { border-color: var(--accent); }
.wiki-card-title { font-size: 14px; font-weight: 600; margin: 7px 0 4px; }
.wiki-card-meta { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.wiki-excerpt {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.45;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Decision blocks */
.decision-block {
  background: rgba(88,166,255,0.05);
  border: 1px solid rgba(88,166,255,0.18);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 11px 14px;
  margin-bottom: 8px;
  transition: border-color 0.15s;
}
.decision-block:hover { border-color: var(--accent); cursor: pointer; }
.decision-text {
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
  margin-bottom: 5px;
  line-height: 1.5;
}
.decision-source {
  font-size: 11px;
  color: var(--text-muted);
}
.decision-source:hover { color: var(--accent); text-decoration: underline; }

/* Sources */
.source-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.source-item:hover { border-color: var(--accent); }
.source-date-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 5px;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
.source-item h3 { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
.source-meta { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.source-excerpt {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  margin-top: 5px;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Keyboard Shortcuts Overlay */
.shortcuts-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: var(--overlay-bg);
  z-index: 400;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(3px);
}
.shortcuts-overlay.open { display: flex; }
.shortcuts-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px 28px;
  min-width: 300px;
  max-width: 420px;
  box-shadow: var(--panel-shadow);
}
.shortcuts-title {
  font-size: 15px;
  font-weight: 700;
  margin-bottom: 18px;
  color: var(--text);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.shortcuts-close {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 16px;
  cursor: pointer;
  padding: 0 2px;
}
.shortcut-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 11px;
  font-size: 13px;
}
.shortcut-key {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: 5px;
  padding: 2px 9px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  color: var(--text);
  min-width: 32px;
  text-align: center;
  flex-shrink: 0;
}
.shortcut-desc { color: var(--text-muted); }

.footer-note { text-align: center; color: var(--text-subtle); font-size: 11px; padding: 28px 0 16px; }

/* ── Activity Tab ────────────────────────────────────────── */
.activity-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; margin-bottom: 18px; }
.activity-feed { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.activity-row {
  display: grid;
  grid-template-columns: 80px 24px 1fr auto;
  gap: 8px;
  align-items: center;
  padding: 7px 12px;
  border-bottom: 1px solid var(--border-muted);
  font-size: 12px;
  transition: background 0.1s;
}
.activity-row:last-child { border-bottom: none; }
.activity-row:nth-child(even) { background: var(--surface); }
.activity-row:nth-child(odd) { background: var(--bg); }
.activity-row:hover { background: var(--surface2); }
.activity-ts { font-size: 10px; color: var(--text-subtle); font-family: 'SFMono-Regular', Consolas, monospace; white-space: nowrap; }
.activity-icon { font-size: 14px; text-align: center; flex-shrink: 0; }
.activity-body { min-width: 0; }
.activity-card-title { font-weight: 500; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 400px; display: inline-block; vertical-align: middle; }
.activity-meta { display: flex; align-items: center; gap: 5px; margin-top: 2px; flex-wrap: wrap; }
.activity-badges { display: flex; align-items: center; gap: 5px; justify-content: flex-end; flex-wrap: wrap; }
.ws-badge {
  display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 3px;
  font-size: 10px; font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase;
  border: 1px solid;
}
.ws-heimdall { background: rgba(88,166,255,0.1); color: #79c0ff; border-color: rgba(88,166,255,0.25); }
.ws-slate { background: rgba(210,153,34,0.1); color: var(--orange); border-color: rgba(210,153,34,0.25); }
.ws-laurion { background: rgba(63,185,80,0.1); color: var(--green); border-color: rgba(63,185,80,0.25); }
.ws-default { background: var(--surface2); color: var(--text-muted); border-color: var(--border); }
.agent-badge {
  display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 3px;
  font-size: 10px; font-weight: 500;
  background: rgba(188,140,255,0.1); color: var(--purple); border: 1px solid rgba(188,140,255,0.25);
}
.transition-badge {
  font-size: 10px; color: var(--text-muted); font-family: 'SFMono-Regular', Consolas, monospace;
  white-space: nowrap;
}
.activity-logs-section { padding: 0 12px 8px; background: var(--surface); border-bottom: 1px solid var(--border-muted); }
.activity-row.has-logs { flex-wrap: wrap; grid-template-columns: 80px 24px 1fr auto; }
.log-toggle-btn {
  background: none; border: none; color: var(--accent); cursor: pointer; font-size: 10px;
  padding: 2px 0; margin-top: 2px; text-decoration: underline; text-underline-offset: 2px;
  display: inline-block;
}
.log-toggle-btn:hover { color: #79c0ff; }
.activity-log-body {
  display: none;
  background: #0d1117; border: 1px solid var(--border);
  border-radius: 4px; padding: 6px 8px; margin-top: 4px;
  max-height: 180px; overflow-y: auto;
  font-family: 'SFMono-Regular', Consolas, monospace; font-size: 11px;
}
.activity-log-body.open { display: block; }
.activity-log-line { display: flex; gap: 8px; padding: 1px 0; color: #8b949e; }
.activity-log-line .log-ts { color: #484f58; flex-shrink: 0; }
.activity-log-line .log-msg { color: #c9d1d9; }
.activity-row-wrap { display: contents; }
/* Full-width log row below main row */
.activity-logrow { grid-column: 1 / -1; padding: 0; }
.activity-empty { text-align: center; padding: 32px 24px; color: var(--text-muted); font-size: 13px; }
.activity-filter-bar { display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.activity-filter-select {
  background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
  padding: 5px 10px; color: var(--text); font-size: 12px; outline: none; cursor: pointer;
}
.activity-filter-select:focus { border-color: var(--accent); }

@media (max-width: 640px) {
  :root { --panel-width: 100vw; }
  .header-tagline { display: none; }
  .knowledge-grid { grid-template-columns: 1fr; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .main-content { padding: 12px; }
  .panel-meta-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<header class="header">
  <div class="header-logo">
    <span>⚒️</span>
    <span>Foundry</span>
  </div>
  <span class="header-tagline">Check in a conversation. Foundry remembers what matters and tracks what needs doing.</span>
  <button class="theme-toggle" id="theme-toggle" onclick="toggleTheme()" title="Toggle light/dark theme"><span id="theme-icon">🌙</span></button>
</header>

<nav class="ws-switcher" id="ws-switcher">
  __WS_OPTIONS__
</nav>

<div id="tabs-container"></div>
<div class="main-content" id="main-content"></div>

<div class="panel-backdrop" id="panel-backdrop" onclick="closePanel()"></div>
<aside class="detail-panel" id="detail-panel">
  <div class="panel-hdr">
    <span class="panel-hdr-title" id="panel-hdr-label">Details</span>
    <button class="panel-close" onclick="closePanel()">✕</button>
  </div>
  <div class="panel-body" id="panel-body"></div>
</aside>

<!-- Keyboard Shortcuts Overlay -->
<div class="shortcuts-overlay" id="shortcuts-overlay" onclick="closeShortcuts()">
  <div class="shortcuts-box" onclick="event.stopPropagation()">
    <div class="shortcuts-title">
      <span>⌨️ Keyboard Shortcuts</span>
      <button class="shortcuts-close" onclick="closeShortcuts()">✕</button>
    </div>
    <div class="shortcut-row"><span class="shortcut-key">Esc</span><span class="shortcut-desc">Close panel or overlay</span></div>
    <div class="shortcut-row"><span class="shortcut-key">?</span><span class="shortcut-desc">Show this shortcuts overlay</span></div>
    <div class="shortcut-row"><span class="shortcut-key">/</span><span class="shortcut-desc">Focus search input</span></div>
    <div class="shortcut-row"><span class="shortcut-key">1</span><span class="shortcut-desc">Switch to Work tab</span></div>
    <div class="shortcut-row"><span class="shortcut-key">2</span><span class="shortcut-desc">Switch to Knowledge tab</span></div>
    <div class="shortcut-row"><span class="shortcut-key">3</span><span class="shortcut-desc">Switch to Sources tab</span></div>
    <div class="shortcut-row"><span class="shortcut-key">4</span><span class="shortcut-desc">Switch to Activity tab</span></div>
  </div>
</div>

<!-- Confirm Delete Modal -->
<div class="confirm-overlay" id="confirm-overlay" onclick="cancelConfirm()">
  <div class="confirm-box" onclick="event.stopPropagation()">
    <div class="confirm-title" id="confirm-title">Delete card?</div>
    <div class="confirm-msg" id="confirm-msg">This will archive the card. It won't appear in the board anymore.</div>
    <div class="confirm-actions">
      <button class="confirm-btn confirm-cancel" onclick="cancelConfirm()">Cancel</button>
      <button class="confirm-btn confirm-danger" id="confirm-action" onclick="execConfirm()">Delete</button>
    </div>
  </div>
</div>

<!-- Toast notifications -->
<div class="toast-container" id="toast-container"></div>

<div class="footer-note" id="footer-note">Generated __BUILD_TS__ · Foundry v4<span id="footer-stats"></span></div>

<script>
window.FOUNDRY_DATA = __FOUNDRY_DATA__;

// ── Utilities ──────────────────────────────────────────────

function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function reltime(ms) {
  if (!ms) return '';
  const s = Math.floor((Date.now() - ms) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago';
  if (s < 7 * 86400) return Math.floor(s/86400) + 'd ago';
  return fmtDate(ms);
}

function fmtDate(ms) {
  if (!ms) return '';
  return new Date(ms).toLocaleDateString('en-GB', {day:'2-digit',month:'short',year:'numeric'});
}

function fmtDateTime(ms) {
  if (!ms) return '';
  const d = new Date(ms);
  return d.toLocaleDateString('en-GB',{day:'2-digit',month:'short'}) + ', ' +
         d.toLocaleTimeString('en-AU',{hour:'2-digit',minute:'2-digit'});
}

function fmtDateSmart(ms) {
  if (!ms) return '';
  const d = new Date(ms);
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const ystStart = todayStart - 86400000;
  const dStart = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const timeStr = d.toLocaleTimeString('en-AU', {hour:'2-digit', minute:'2-digit'});
  if (dStart === todayStart) return 'Today, ' + timeStr;
  if (dStart === ystStart) return 'Yesterday, ' + timeStr;
  return fmtDate(ms);
}

function fmtDuration(s, e) {
  if (!s || !e) return '';
  const sec = Math.floor((e - s) / 1000);
  if (sec < 60) return sec + 's';
  if (sec < 3600) return Math.floor(sec/60) + 'm ' + (sec%60) + 's';
  return Math.floor(sec/3600) + 'h ' + Math.floor((sec%3600)/60) + 'm';
}

function fmtBytes(b) {
  if (!b) return '0B';
  if (b < 1024) return b + 'B';
  if (b < 1048576) return (b/1024).toFixed(1) + 'KB';
  return (b/1048576).toFixed(1) + 'MB';
}

// ── Cost formatting ────────────────────────────────────────

function fmtCost(v) {
  if (v == null) return '';
  if (v < 0.01) return '<$0.01';
  if (v < 1) return '$' + v.toFixed(2);
  return '$' + v.toFixed(2);
}

function fmtTokensShort(n) {
  if (!n) return '0';
  if (n < 1000) return String(n);
  if (n < 1_000_000) return (n/1000).toFixed(1).replace(/\.0$/,'') + 'K';
  return (n/1_000_000).toFixed(1).replace(/\.0$/,'') + 'M';
}

function fmtTokensLong(n) {
  if (!n) return '0';
  return n.toLocaleString();
}

function costBadgeHtml(c) {
  if (!c || !c.cost) return '';
  const cost = c.cost;
  return `<span class="kanban-card-cost" title="${fmtTokensLong(cost.input_tokens)} in · ${fmtTokensLong(cost.output_tokens)} out · ${cost.turns} turns">`
    + `${fmtCost(cost.cost)}`
    + `<span class="cost-tokens">${fmtTokensShort(cost.input_tokens + cost.output_tokens)} tok</span>`
    + `</span>`;
}

function costBreakdownHtml(c) {
  if (!c || !c.cost) return '';
  const cost = c.cost;
  const total = cost.total_tokens || 1;
  const inPct = Math.round((cost.input_tokens / total) * 100);
  const outPct = Math.round((cost.output_tokens / total) * 100);
  const crPct = Math.round((cost.cache_read / total) * 100);
  const cwPct = Math.max(0, 100 - inPct - outPct - crPct);

  return `<div class="panel-section">
    <div class="panel-sec-title">💰 Cost & Token Usage</div>
    <div class="cost-breakdown">
      <div class="cost-stat">
        <div class="cost-stat-value cost-primary">${fmtCost(cost.cost)}</div>
        <div class="cost-stat-label">List Price</div>
      </div>
      <div class="cost-stat">
        <div class="cost-stat-value">${fmtTokensShort(cost.input_tokens)}</div>
        <div class="cost-stat-label">Input Tokens</div>
      </div>
      <div class="cost-stat">
        <div class="cost-stat-value">${fmtTokensShort(cost.output_tokens)}</div>
        <div class="cost-stat-label">Output Tokens</div>
      </div>
      <div class="cost-stat">
        <div class="cost-stat-value">${fmtTokensShort(cost.cache_read)}</div>
        <div class="cost-stat-label">Cache Read</div>
      </div>
      <div class="cost-stat">
        <div class="cost-stat-value">${cost.turns}</div>
        <div class="cost-stat-label">Turns</div>
      </div>
      <div class="cost-stat">
        <div class="cost-stat-value">${esc(cost.model || '—')}</div>
        <div class="cost-stat-label">Model</div>
      </div>
    </div>
    <div class="cost-bar">
      <div class="cost-bar-seg cb-input" style="width:${inPct}%" title="Input: ${fmtTokensLong(cost.input_tokens)}"></div>
      <div class="cost-bar-seg cb-output" style="width:${outPct}%" title="Output: ${fmtTokensLong(cost.output_tokens)}"></div>
      <div class="cost-bar-seg cb-cache-read" style="width:${crPct}%" title="Cache read: ${fmtTokensLong(cost.cache_read)}"></div>
      <div class="cost-bar-seg cb-cache-write" style="width:${cwPct}%" title="Cache write: ${fmtTokensLong(cost.cache_write)}"></div>
    </div>
    <div class="cost-bar-legend">
      <span><span class="cost-bar-legend-dot" style="background:var(--accent)"></span>Input (${fmtTokensShort(cost.input_tokens)})</span>
      <span><span class="cost-bar-legend-dot" style="background:var(--green)"></span>Output (${fmtTokensShort(cost.output_tokens)})</span>
      <span><span class="cost-bar-legend-dot" style="background:var(--orange);opacity:0.6"></span>Cache Read (${fmtTokensShort(cost.cache_read)})</span>
      <span><span class="cost-bar-legend-dot" style="background:var(--purple);opacity:0.6"></span>Cache Write (${fmtTokensShort(cost.cache_write)})</span>
    </div>
    <div style="margin-top:8px;font-size:10px;color:var(--text-subtle)">List-price equivalent (Max subscription actual cost: $0)</div>
  </div>`;
}

// Extract "**Decision:**" or "Decision:" lines from page bodies
function extractDecisions(pages) {
  const decisions = [];
  for (const p of pages) {
    if (!p.body) continue;
    const lines = p.body.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const m = lines[i].match(/\*\*Decision:\*\*\s*(.+)/) ||
                lines[i].match(/^Decision:\s*(.+)/i);
      if (m) {
        decisions.push({ text: m[1].trim(), page: p });
      }
    }
  }
  return decisions;
}

// Parse structured sections from card notes
function parseNotesSections(notes) {
  if (!notes) return { objective: null, dod: null, sourceRef: null };
  // Match "Objective:" possibly with ** markdown around it
  const objM = notes.match(/(?:^|\n)\*{0,2}Objective:\*{0,2}\s+([^\n]+(?:\n(?![A-Z\*])[^\n]+)*)/i);
  // Match "Definition of Done:" block
  const dodM = notes.match(/(?:^|\n)\*{0,2}Definition of Done:\*{0,2}\s+([\s\S]+?)(?=\n\n|\n\*{0,2}[A-Z]|$)/i);
  // Match "Source: src_xxx"
  const srcM = notes.match(/\bSource:\s*(src_[a-zA-Z0-9_-]+)/i);
  return {
    objective: objM ? objM[1].trim() : null,
    dod: dodM ? dodM[1].trim() : null,
    sourceRef: srcM ? srcM[1] : null
  };
}

// Strip markdown for plain-text excerpts
function stripMarkdown(text) {
  if (!text) return '';
  return text
    .replace(/<!--\s*openclaw:wiki:[^>]*-->/g, '')  // strip wiki markers
    .replace(/^---[\s\S]*?---\n?/, '')      // strip frontmatter if any
    .replace(/```[\s\S]*?```/g, '')          // strip code blocks
    .replace(/#+\s+[^\n]+/g, '')             // strip headings
    .replace(/\*\*([^*]+)\*\*/g, '$1')       // bold
    .replace(/\*([^*]+)\*/g, '$1')           // italic
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // links
    .replace(/^\s*[-*]\s+/gm, '')            // list markers
    .replace(/^\s*\d+\.\s+/gm, '')           // numbered lists
    .replace(/\n{2,}/g, ' ')                 // collapse newlines
    .replace(/\s+/g, ' ')
    .trim();
}

// Simple markdown → HTML
function mdToHtml(text) {
  if (!text) return '';
  // Strip openclaw wiki managed-block markers before escaping
  let t = text.replace(/<!--\s*openclaw:wiki:[^>]*-->/g, '');
  t = t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  t = t.replace(/```([\s\S]*?)```/g, (_,c) => '<pre><code>' + c.trim() + '</code></pre>');
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  t = t.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  t = t.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  t = t.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/\*(.+?)\*/g, '<em>$1</em>');
  t = t.replace(/__(.+?)__/g, '<strong>$1</strong>');
  t = t.replace(/(^|\s)_([^_]+?)_(\s|$|[.,;:!?)])/g, '$1<em>$2</em>$3');
  t = t.replace(/^---$/gm, '<hr>');
  t = t.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');
  t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  const lines = t.split('\n');
  const out = []; let inUl = false, inOl = false, inTable = false;

  function parseTableRow(line) {
    let cells = line.replace(/^\|/, '').replace(/\|$/, '').split('|');
    return cells.map(c => c.trim());
  }
  function isTableSep(line) { return /^\|?[\s:]*-{2,}[\s:|-]*\|?$/.test(line.trim()); }
  function isTableRow(line) { return /^\|.*\|/.test(line.trim()); }
  function parseAlign(sepLine) {
    return parseTableRow(sepLine).map(c => {
      c = c.trim();
      if (c.startsWith(':') && c.endsWith(':')) return 'center';
      if (c.endsWith(':')) return 'right';
      return 'left';
    });
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // Detect markdown table: current line is a pipe row, next line is separator
    if (!inTable && isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i+1])) {
      if (inUl) { out.push('</ul>'); inUl = false; }
      if (inOl) { out.push('</ol>'); inOl = false; }
      inTable = true;
      const headers = parseTableRow(line);
      const aligns = parseAlign(lines[i+1]);
      i++; // skip separator line
      out.push('<div class="md-table-wrap"><table class="md-table">');
      out.push('<thead><tr>' + headers.map((h,j) =>
        `<th${aligns[j]&&aligns[j]!=='left'?' style="text-align:'+aligns[j]+'"':''}>` + h + '</th>'
      ).join('') + '</tr></thead>');
      out.push('<tbody>');
      // Consume remaining table rows
      while (i + 1 < lines.length && isTableRow(lines[i+1])) {
        i++;
        const cells = parseTableRow(lines[i]);
        out.push('<tr>' + cells.map((c,j) =>
          `<td${aligns[j]&&aligns[j]!=='left'?' style="text-align:'+aligns[j]+'"':''}>` + c + '</td>'
        ).join('') + '</tr>');
      }
      out.push('</tbody></table></div>');
      inTable = false;
      continue;
    }
    if (/^\s*[-*] /.test(line)) {
      if (inOl) { out.push('</ol>'); inOl = false; }
      if (!inUl) { out.push('<ul>'); inUl = true; }
      out.push('<li>' + line.replace(/^\s*[-*] /, '') + '</li>');
    } else if (/^\s*\d+\. /.test(line)) {
      if (inUl) { out.push('</ul>'); inUl = false; }
      if (!inOl) { out.push('<ol>'); inOl = true; }
      out.push('<li>' + line.replace(/^\s*\d+\. /, '') + '</li>');
    } else {
      if (inUl) { out.push('</ul>'); inUl = false; }
      if (inOl) { out.push('</ol>'); inOl = false; }
      if (line.trim() === '') out.push('');
      else if (line.startsWith('<')) out.push(line);
      else out.push('<p>' + line + '</p>');
    }
  }
  if (inUl) out.push('</ul>');
  if (inOl) out.push('</ol>');
  return out.join('\n');
}

// Deterministic agent colors
const ACOLS = [
  ['rgba(88,166,255,.15)','#58a6ff','rgba(88,166,255,.3)'],
  ['rgba(188,140,255,.15)','#bc8cff','rgba(188,140,255,.3)'],
  ['rgba(63,185,80,.12)','#3fb950','rgba(63,185,80,.25)'],
  ['rgba(210,153,34,.15)','#d29922','rgba(210,153,34,.3)'],
  ['rgba(255,123,114,.15)','#ff7b72','rgba(255,123,114,.3)'],
  ['rgba(121,192,255,.15)','#79c0ff','rgba(121,192,255,.3)'],
];
function agentColIdx(id) {
  if (!id) return 0;
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) & 0xffff;
  return h % ACOLS.length;
}
function agentPill(id) {
  if (!id) return '';
  const [bg, col, border] = ACOLS[agentColIdx(id)];
  return `<span class="pill" style="background:${bg};color:${col};border:1px solid ${border}">${esc(id)}</span>`;
}

function statusPill(s) {
  const L = {running:'🔨 Running', blocked:'🚫 Blocked', done:'✅ Done', ready:'🟢 Ready', review:'👀 Review', todo:'📋 Todo', scheduled:'📅 Scheduled'};
  return `<span class="pill ps-${esc(s)}">${L[s] || esc(s)}</span>`;
}
function priorityPill(p) {
  const L = {urgent:'🔴 Urgent', high:'🟠 High', normal:'Normal', low:'🟢 Low'};
  return `<span class="pill pp-${esc(p)}">${L[p] || esc(p)}</span>`;
}
function labelPill(l) { return `<span class="pill pl-label">${esc(l)}</span>`; }

function attachIcon(mime) {
  if (!mime) return '📎';
  if (mime.startsWith('image/')) return '🖼️';
  if (mime === 'application/pdf') return '📄';
  if (mime.startsWith('text/')) return '📝';
  if (mime.includes('json') || mime.includes('javascript')) return '🔧';
  if (mime.includes('zip') || mime.includes('tar')) return '📦';
  return '📎';
}

// ── State ──────────────────────────────────────────────────

let CWS = null;              // current workspace id
let CTAB = 'work';           // current inner tab
let F_STATUS = 'all';        // work: status filter
let F_PRIO = 'all';          // work: priority filter
let F_AGENT = 'all';         // work: agent filter
let F_SEARCH = '';           // work: search
let F_WIKI = '';             // knowledge: search
let F_FOLDER = 'all';        // knowledge: folder filter
let F_WIKI_TYPE = 'all';     // knowledge: page type filter
let F_DECISION = false;      // knowledge: decision view toggle
let F_SOURCE_SEARCH = '';    // sources: search
let searchTimer = null;

// ── Workspace / Tab Switching ──────────────────────────────

function initApp() {
  const ids = Object.keys(window.FOUNDRY_DATA.workspaces);
  if (!ids.length) return;
  CWS = ids[0];
  renderWorkspace();
}

function switchWs(wsId, btn) {
  CWS = wsId; CTAB = 'work';
  F_STATUS = 'all'; F_PRIO = 'all'; F_AGENT = 'all'; F_SEARCH = ''; F_WIKI = '';
  F_FOLDER = 'all'; F_WIKI_TYPE = 'all'; F_DECISION = false; F_SOURCE_SEARCH = '';
  document.querySelectorAll('.ws-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderWorkspace();
}

function switchTab(tab) {
  CTAB = tab;
  renderWorkspace();
}

function renderWorkspace() {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  if (!ws) return;
  const cards = ws.cards || [];
  const pages = ws.pages || [];
  const knowledge = pages.filter(p => p.folder !== 'sources');
  const sources = pages.filter(p => p.folder === 'sources');

  // Count total events across ALL workspaces for Activity badge
  const allEventsCount = Object.values(window.FOUNDRY_DATA.workspaces)
    .flatMap(w => (w.cards||[]).flatMap(c => c.events||[])).length;

  document.getElementById('tabs-container').innerHTML = `
    <nav class="inner-tabs">
      <div class="itab ${CTAB==='work'?'active':''}" onclick="switchTab('work')">
        Work <span class="badge-count">${cards.length}</span>
      </div>
      <div class="itab ${CTAB==='knowledge'?'active':''}" onclick="switchTab('knowledge')">
        Knowledge <span class="badge-count">${knowledge.length}</span>
      </div>
      <div class="itab ${CTAB==='sources'?'active':''}" onclick="switchTab('sources')">
        Sources <span class="badge-count">${sources.length}</span>
      </div>
      <div class="itab ${CTAB==='activity'?'active':''}" onclick="switchTab('activity')">
        Activity <span class="badge-count">${allEventsCount}</span>
      </div>
    </nav>`;

  // Update footer stats
  const statsEl = document.getElementById('footer-stats');
  if (statsEl) {
    statsEl.textContent = ` · ${cards.length} cards · ${knowledge.length} pages · ${sources.length} sources`;
  }

  const mc = document.getElementById('main-content');
  if (CTAB === 'work') { renderWork(); }
  else if (CTAB === 'activity') { mc.classList.remove('kanban-mode'); renderActivity(); }
  else { mc.classList.remove('kanban-mode'); if (CTAB === 'knowledge') renderKnowledge(); else renderSources(); }
}

// ── Work Tab ───────────────────────────────────────────────

const KANBAN_COLUMNS = [
  { id: 'scheduled', label: 'Scheduled', dot: 'd-scheduled' },
  { id: 'todo',      label: 'To Do',     dot: 'd-todo' },
  { id: 'ready',     label: 'Ready',     dot: 'd-ready' },
  { id: 'running',   label: 'Running',   dot: 'd-running' },
  { id: 'review',    label: 'Review',    dot: 'd-review' },
  { id: 'blocked',   label: 'Blocked',   dot: 'd-blocked' },
  { id: 'done',      label: 'Done',      dot: 'd-done' },
];

function renderWork() {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const all = ws.cards || [];
  const mc = document.getElementById('main-content');
  mc.classList.add('kanban-mode');

  const byStatus = s => all.filter(c => c.status === s).length;
  const running = byStatus('running'), blocked = byStatus('blocked'), done = byStatus('done');
  const active = all.filter(c => c.status !== 'done').length;

  const agents = [...new Set(all.map(c => c.agent_id).filter(Boolean))].sort();

  // Apply filters (except status — kanban shows all columns)
  let cards = all;
  if (F_PRIO !== 'all') cards = cards.filter(c => c.priority === F_PRIO);
  if (F_AGENT !== 'all') cards = cards.filter(c => c.agent_id === F_AGENT);
  if (F_SEARCH) {
    const q = F_SEARCH.toLowerCase();
    cards = cards.filter(c =>
      (c.title||'').toLowerCase().includes(q) ||
      (c.notes||'').toLowerCase().includes(q) ||
      (c.id||'').toLowerCase().includes(q) ||
      (c.labels||[]).some(l => l.toLowerCase().includes(q))
    );
  }

  // Group by status
  const grouped = {};
  for (const col of KANBAN_COLUMNS) grouped[col.id] = [];
  for (const c of cards) {
    const s = c.status || 'todo';
    if (grouped[s]) grouped[s].push(c);
    else if (grouped['todo']) grouped['todo'].push(c);
  }

  const statCard = (val, label, cls='') => {
    const hasVal = val > 0;
    const statCls = hasVal ? `has-value ${cls}` : '';
    const valCls = hasVal && cls ? `c-${cls}` : (hasVal ? 'c-accent' : '');
    return `<div class="stat-card ${statCls}"><div class="stat-value ${valCls}">${val}</div><div class="stat-label">${label}</div></div>`;
  };

  const statsHtml = `<div class="stats-grid">
    ${statCard(active,'Active')}
    ${statCard(running,'Running')}
    ${statCard(blocked,'Blocked','red')}
    ${statCard(done,'Done','green')}
    <div class="stat-card"><div class="stat-value">${all.length}</div><div class="stat-label">Total</div></div>
  </div>`;

  const agentOpts = agents.map(a =>
    `<option value="${esc(a)}" ${F_AGENT===a?'selected':''}>${esc(a)}</option>`
  ).join('');

  const controlsHtml = `
    <div class="controls-bar">
      <div class="search-wrap">
        <span class="search-icon">🔍</span>
        <input class="search-input" id="work-search" type="search" placeholder="Search cards…"
          value="${esc(F_SEARCH)}" oninput="debSearch(this.value)">
      </div>
      <select class="filter-select" onchange="setPrio(this.value)">
        <option value="all" ${F_PRIO==='all'?'selected':''}>All priorities</option>
        <option value="urgent" ${F_PRIO==='urgent'?'selected':''}>🔴 Urgent</option>
        <option value="high" ${F_PRIO==='high'?'selected':''}>🟠 High</option>
        <option value="normal" ${F_PRIO==='normal'?'selected':''}>Normal</option>
        <option value="low" ${F_PRIO==='low'?'selected':''}>🟢 Low</option>
      </select>
      ${agents.length ? `<select class="filter-select" onchange="setAgent(this.value)">
        <option value="all" ${F_AGENT==='all'?'selected':''}>All agents</option>
        ${agentOpts}
      </select>` : ''}
      <button class="dispatch-btn" onclick="dispatchAll()" title="Run dispatch pass — promote ready cards and start work">▶ Dispatch</button>
    </div>`;

  // Always show core workflow columns; hide scheduled/done only if empty
  const ALWAYS_SHOW = ['todo','ready','running','review','blocked'];
  const visibleCols = F_STATUS !== 'all'
    ? KANBAN_COLUMNS.filter(col => col.id === F_STATUS)
    : KANBAN_COLUMNS.filter(col => ALWAYS_SHOW.includes(col.id) || grouped[col.id].length > 0);

  const statusFilterHtml = `<div class="status-filters">
    ${['all',...KANBAN_COLUMNS.map(c=>c.id)].map(s => {
      const cnt = s === 'all' ? all.length : byStatus(s);
      if (s !== 'all' && cnt === 0 && !['running','blocked','review','ready','todo','done'].includes(s)) return '';
      return `<button class="sf-btn ${F_STATUS===s?'active':''}" data-s="${s}"
        onclick="setStatus('${s}')">${s==='all'?'All':s.charAt(0).toUpperCase()+s.slice(1)}
        ${s!=='all'?`<span style="opacity:.65">(${cnt})</span>`:''}</button>`;
    }).join('')}
  </div>`;

  const columnsHtml = visibleCols.map(col => {
    const colCards = grouped[col.id] || [];
    return `<div class="kanban-col"
      ondragover="onColDragOver(event)"
      ondragleave="onColDragLeave(event)"
      ondrop="onColDrop(event,'${col.id}')">
      <div class="kanban-col-header">
        <span class="kanban-col-dot ${col.dot}"></span>
        <span class="kanban-col-name">${col.label}</span>
        <span class="kanban-col-count">${colCards.length}</span>
      </div>
      <div class="kanban-col-body">
        ${colCards.map(c => kanbanCardHtml(c)).join('')}
      </div>
    </div>`;
  }).join('');

  const boardHtml = cards.length === 0 && !F_SEARCH && F_PRIO === 'all' && F_AGENT === 'all'
    ? `<div class="empty-state">
        <div class="empty-icon">📋</div>
        <p>No cards in this workspace yet.</p>
      </div>`
    : `<div class="kanban-board">${columnsHtml}</div>`;

  mc.innerHTML = statsHtml + controlsHtml + statusFilterHtml + boardHtml;
}

function resetWorkFilters() {
  F_STATUS = 'all'; F_PRIO = 'all'; F_AGENT = 'all'; F_SEARCH = '';
  renderWork();
}

function cardItemHtml(c) {
  const short = (c.id||'').slice(0,8);
  const notes = c.notes || '';
  const preview = notes.length > 200
    ? notes.slice(0, notes.lastIndexOf(' ', 200) || 200) + '…'
    : notes;
  const labels = (c.labels||[]).map(l => labelPill(l)).join('');
  const srcBtn = c.source_url
    ? `<span class="pill pl-source" onclick="event.stopPropagation();window.open('${esc(c.source_url)}','_blank')" title="${esc(c.source_url)}">↗ source</span>`
    : '';
  const failBadge = (c.failure_count > 0)
    ? `<span class="pill" style="background:rgba(248,81,73,.1);color:#ff7b72;border:1px solid rgba(248,81,73,.2);font-size:10px">⚠ ${c.failure_count} fail${c.failure_count!==1?'s':''}</span>`
    : '';

  return `<div class="card-item s-${c.status}" onclick="openCard('${esc(c.id)}')">
    <div class="card-row1">
      ${statusPill(c.status)}
      ${priorityPill(c.priority)}
      ${agentPill(c.agent_id)}
      ${labels}
      ${srcBtn}
    </div>
    <div class="card-title">${esc(c.title)}</div>
    ${preview ? `<div class="card-notes">${esc(preview)}</div>` : ''}
    <div class="card-row2">
      <span class="card-id">#${short}</span>
      ${failBadge}
      <span class="card-date">${reltime(c.updated_at)}</span>
    </div>
  </div>`;
}

function kanbanCardHtml(c) {
  const short = (c.id||'').slice(0,8);
  const labels = (c.labels||[]).slice(0,3).map(l => labelPill(l)).join('');
  const failBadge = (c.failure_count > 0)
    ? `<span class="pill" style="background:rgba(248,81,73,.1);color:#ff7b72;border:1px solid rgba(248,81,73,.2);font-size:10px">⚠ ${c.failure_count}</span>`
    : '';
  const childCount = (c.children||[]).length;
  const childBadge = childCount > 0
    ? `<span style="font-size:10px;color:var(--text-subtle)" title="${childCount} sub-card${childCount!==1?'s':''}">📌${childCount}</span>`
    : '';

  const safeTitle = esc(c.title).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
  return `<div class="kanban-card s-${c.status}" draggable="true"
    onclick="openCard('${esc(c.id)}')"
    ondragstart="onDragStart(event,'${esc(c.id)}')"
    ondragend="onDragEnd(event)">
    ${(c.status==='ready'||c.status==='todo') ? `<button class="kanban-card-play" onclick="dispatchCard(event,'${esc(c.id)}')" title="Start this card">▶</button>` : ''}
    <button class="kanban-card-delete" onclick="promptDelete(event,'${esc(c.id)}','${safeTitle}')" title="Archive card">🗑</button>
    <div class="kanban-card-pills">
      ${priorityPill(c.priority)}
      ${agentPill(c.agent_id)}
      ${labels}
      ${failBadge}
    </div>
    <div class="kanban-card-title">${esc(c.title)}</div>
    <div class="kanban-card-footer">
      <span class="kanban-card-id">#${short}</span>
      ${childBadge}
      ${costBadgeHtml(c)}
      <span class="kanban-card-date">${reltime(c.updated_at)}</span>
    </div>
  </div>`;
}

// ── Knowledge Tab ──────────────────────────────────────────

function renderKnowledge() {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const all = (ws.pages||[]).filter(p => p.folder !== 'sources');

  // Count by folder
  const byFolder = {};
  for (const p of all) { byFolder[p.folder] = (byFolder[p.folder]||0) + 1; }

  // Known main folders + any extras
  const MAIN_FOLDERS = ['entities','concepts','syntheses','reports'];
  const allFolderKeys = Object.keys(byFolder).filter(f => f !== 'root').sort();
  const mainPresent = MAIN_FOLDERS.filter(f => byFolder[f]);
  const otherFolders = allFolderKeys.filter(f => !MAIN_FOLDERS.includes(f));
  const displayFolders = [...mainPresent, ...otherFolders];

  // Count by page type
  const pageTypes = [...new Set(all.map(p => p.pageType).filter(Boolean))].sort();

  // Stats
  const cnt = f => (byFolder[f]||0);
  const kStat = (val, label, cls='') => {
    const hv = val > 0 ? `has-value ${cls}` : '';
    const vc = val > 0 && cls ? `c-${cls}` : (val > 0 ? 'c-accent' : '');
    return `<div class="stat-card ${hv}"><div class="stat-value ${vc}">${val}</div><div class="stat-label">${label}</div></div>`;
  };
  const statsHtml = `<div class="stats-grid">
    ${kStat(cnt('entities'), 'Entities')}
    ${kStat(cnt('concepts'), 'Concepts', 'orange')}
    ${kStat(cnt('syntheses'), 'Syntheses', 'green')}
    ${kStat(cnt('reports'), 'Reports')}
    ${kStat(all.length, 'Total Pages')}
  </div>`;

  // Decisions for count badge
  const allDecisions = extractDecisions(all);

  // Folder pills
  const folderPills = `<div class="folder-filters">
    <button class="ff-btn ${F_FOLDER==='all'&&!F_DECISION?'active':''}" onclick="setFolder('all')">All (${all.length})</button>
    ${displayFolders.map(f =>
      `<button class="ff-btn ${F_FOLDER===f&&!F_DECISION?'active':''}" onclick="setFolder('${esc(f)}')">${f.charAt(0).toUpperCase()+f.slice(1)} (${cnt(f)})</button>`
    ).join('')}
    <button class="ff-btn decision-btn ${F_DECISION?'active':''}" onclick="toggleDecision()">📋 Decisions (${allDecisions.length})</button>
  </div>`;

  // Controls: search + optional type filter
  const typeFilter = pageTypes.length > 2 ? `
    <select class="filter-select" onchange="setWikiType(this.value)">
      <option value="all" ${F_WIKI_TYPE==='all'?'selected':''}>All types</option>
      ${pageTypes.map(t => `<option value="${esc(t)}" ${F_WIKI_TYPE===t?'selected':''}>${esc(t)}</option>`).join('')}
    </select>` : '';

  const searchHtml = `<div class="controls-bar" style="margin-bottom:8px">
    <div class="search-wrap">
      <span class="search-icon">🔍</span>
      <input class="search-input" id="wiki-search" type="search" placeholder="Search knowledge…"
        value="${esc(F_WIKI)}" oninput="debWiki(this.value)">
    </div>
    ${typeFilter}
  </div>`;

  // Decision view
  if (F_DECISION) {
    let decisions = allDecisions;
    if (F_WIKI) {
      const q = F_WIKI.toLowerCase();
      decisions = decisions.filter(d =>
        d.text.toLowerCase().includes(q) ||
        d.page.title.toLowerCase().includes(q)
      );
    }
    const decisionsHtml = decisions.length === 0
      ? `<div class="empty-state">
          <div class="empty-icon">📋</div>
          <p>${F_WIKI ? 'No decisions match your search.' : 'No decision records found. Mark decisions with <code>**Decision:** text</code> in page bodies.'}</p>
         </div>`
      : decisions.map(d =>
          `<div class="decision-block" onclick="openPage('${esc(encodePageId(d.page))}')">
            <div class="decision-text">${esc(d.text)}</div>
            <div class="decision-source">
              📄 ${esc(d.page.title)}${d.page.folder && d.page.folder !== 'root' ? ` <span style="opacity:.7">· ${esc(d.page.folder)}</span>` : ''}
            </div>
          </div>`
        ).join('');

    document.getElementById('main-content').innerHTML = statsHtml + folderPills + searchHtml + decisionsHtml;
    return;
  }

  // Normal page grid view — apply filters
  let pages = all;
  if (F_FOLDER !== 'all') pages = pages.filter(p => p.folder === F_FOLDER);
  if (F_WIKI_TYPE !== 'all') pages = pages.filter(p => p.pageType === F_WIKI_TYPE);
  if (F_WIKI) {
    const q = F_WIKI.toLowerCase();
    pages = pages.filter(p =>
      (p.title||'').toLowerCase().includes(q) ||
      (p.body||'').toLowerCase().includes(q) ||
      (p.entityType||'').toLowerCase().includes(q)
    );
  }

  const gridHtml = pages.length === 0
    ? `<div class="empty-state">
        <div class="empty-icon">📚</div>
        <p>No pages match your search.</p>
        ${F_WIKI || F_FOLDER !== 'all' || F_WIKI_TYPE !== 'all' ? `<div class="empty-actions">
          ${F_WIKI ? `<button class="empty-action-btn" onclick="F_WIKI='';renderKnowledge()">Clear search</button>` : ''}
          ${F_FOLDER !== 'all' ? `<button class="empty-action-btn" onclick="setFolder('all')">Clear folder filter</button>` : ''}
          ${F_WIKI_TYPE !== 'all' ? `<button class="empty-action-btn" onclick="setWikiType('all')">Clear type filter</button>` : ''}
        </div>` : ''}
       </div>`
    : `<div class="knowledge-grid">${pages.map(p => wikiCardHtml(p)).join('')}</div>`;

  document.getElementById('main-content').innerHTML = statsHtml + folderPills + searchHtml + gridHtml;
}

function wikiCardHtml(p) {
  const pid = encodePageId(p);
  const excerpt = p.body ? stripMarkdown(p.body).slice(0, 120) : '';
  const showEllipsis = p.body && stripMarkdown(p.body).length > 120;
  return `<div class="wiki-card" onclick="openPage('${esc(pid)}')">
    <div>
      <span class="badge badge-${esc(p.pageType||'unknown')}">${esc(p.pageType||'?')}</span>
      ${p.folder && p.folder !== 'root' ? `<span class="badge badge-muted">${esc(p.folder)}</span>` : ''}
      ${p.status ? `<span class="badge badge-muted">${esc(p.status)}</span>` : ''}
    </div>
    <div class="wiki-card-title">${esc(p.title)}</div>
    ${excerpt ? `<div class="wiki-excerpt">${esc(excerpt)}${showEllipsis ? '…' : ''}</div>` : ''}
    <div class="wiki-card-meta">${p.entityType ? esc(p.entityType)+' · ' : ''}${p.updatedAt ? esc(p.updatedAt.slice(0,10)) : ''}</div>
  </div>`;
}

// ── Sources Tab ────────────────────────────────────────────

function renderSources() {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const all = (ws.pages||[]).filter(p => p.folder === 'sources');

  // "This month" count
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const thisMonth = all.filter(s => {
    if (!s.updatedAt) return false;
    const d = new Date(s.updatedAt);
    return !isNaN(d.getTime()) && d.getTime() >= monthStart;
  }).length;

  const statsHtml = `<div class="stats-grid">
    <div class="stat-card ${all.length>0?'has-value':''}">
      <div class="stat-value ${all.length>0?'c-accent':''}">${all.length}</div>
      <div class="stat-label">Total Sources</div>
    </div>
    <div class="stat-card ${thisMonth>0?'has-value c-green':''}">
      <div class="stat-value ${thisMonth>0?'c-green':''}">${thisMonth}</div>
      <div class="stat-label">This Month</div>
    </div>
  </div>`;

  const searchHtml = `<div class="controls-bar" style="margin-bottom:14px">
    <div class="search-wrap">
      <span class="search-icon">🔍</span>
      <input class="search-input" id="source-search" type="search" placeholder="Search sources…"
        value="${esc(F_SOURCE_SEARCH)}" oninput="debSource(this.value)">
    </div>
  </div>`;

  // Apply search filter
  let sources = all;
  if (F_SOURCE_SEARCH) {
    const q = F_SOURCE_SEARCH.toLowerCase();
    sources = sources.filter(s =>
      (s.title||'').toLowerCase().includes(q) ||
      (s.body||'').toLowerCase().includes(q)
    );
  }

  // Sort by updatedAt descending
  sources = [...sources].sort((a, b) => {
    const da = a.updatedAt ? new Date(a.updatedAt).getTime() : 0;
    const db = b.updatedAt ? new Date(b.updatedAt).getTime() : 0;
    return db - da;
  });

  const itemsHtml = sources.length === 0
    ? `<div class="empty-state">
        <div class="empty-icon">📰</div>
        <p>${F_SOURCE_SEARCH ? 'No sources match your search.' : 'No sources committed yet.'}</p>
        ${F_SOURCE_SEARCH ? `<div class="empty-actions"><button class="empty-action-btn" onclick="F_SOURCE_SEARCH='';renderSources()">Clear search</button></div>` : ''}
       </div>`
    : sources.map(s => {
        const pid = encodePageId(s);
        const excerpt = s.body ? stripMarkdown(s.body).slice(0, 280) : '';
        const showEllipsis = s.body && stripMarkdown(s.body).length > 280;
        const dateStr = s.updatedAt ? s.updatedAt.slice(0, 10) : '';
        // Show entityType if present, skip redundant 'source' pageType (already on Sources tab)
        const metaParts = [];
        if (s.entityType) metaParts.push(esc(s.entityType));
        if (s.pageType && s.pageType !== 'unknown' && s.pageType !== 'source') metaParts.push(esc(s.pageType));
        const metaStr = metaParts.join(' · ');
        return `<div class="source-item" onclick="openPage('${esc(pid)}')">
          ${dateStr ? `<div class="source-date-badge">${esc(dateStr)}</div>` : ''}
          <h3>${esc(s.title)}</h3>
          ${excerpt ? `<div class="source-excerpt">${esc(excerpt)}${showEllipsis ? '…' : ''}</div>` : ''}
          ${metaStr ? `<div class="source-meta">${metaStr}</div>` : ''}
        </div>`;
      }).join('');

  document.getElementById('main-content').innerHTML = statsHtml + searchHtml + itemsHtml;
}

// ── Panel: Card Detail ─────────────────────────────────────

function openCard(cardId) {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const card = (ws.cards||[]).find(c => c.id === cardId);
  if (!card) return;
  document.getElementById('panel-hdr-label').textContent = 'Card Details';
  document.getElementById('panel-body').innerHTML = cardPanelHtml(card);
  openPanel();
}

function cardPanelHtml(c) {
  const short = (c.id||'').slice(0,8);

  const metaGrid = `<div class="panel-meta-grid">
    <div><div class="pm-label">Status</div><div class="pm-value">${statusPill(c.status)}</div></div>
    <div><div class="pm-label">Priority</div><div class="pm-value">${priorityPill(c.priority)}</div></div>
    <div><div class="pm-label">Agent</div><div class="pm-value">${c.agent_id ? agentPill(c.agent_id) : '<span style="color:var(--text-muted)">—</span>'}</div></div>
    <div><div class="pm-label">Updated</div><div class="pm-value" style="font-size:11px;color:var(--text-muted)">${fmtDateSmart(c.updated_at)}</div></div>
    ${c.started_at ? `<div><div class="pm-label">Started</div><div class="pm-value" style="font-size:11px;color:var(--text-muted)">${fmtDateSmart(c.started_at)}</div></div>` : ''}
    ${c.completed_at ? `<div><div class="pm-label">Completed</div><div class="pm-value" style="font-size:11px;color:var(--text-muted)">${fmtDateSmart(c.completed_at)}</div></div>` : ''}
    <div><div class="pm-label">Card ID</div><div class="pm-value" style="font-family:monospace;font-size:11px;color:var(--text-muted)">${esc(short)}</div></div>
    ${c.failure_count > 0 ? `<div><div class="pm-label">Failures</div><div class="pm-value" style="color:var(--red)">${c.failure_count}</div></div>` : ''}
  </div>`;

  const labelsHtml = (c.labels||[]).length > 0
    ? `<div class="panel-labels" style="margin-bottom:10px">${(c.labels||[]).map(l => labelPill(l)).join('')}</div>`
    : '';

  const srcHtml = c.source_url
    ? `<div style="margin-bottom:10px"><a href="${esc(c.source_url)}" target="_blank" class="pill pl-source">↗ View source</a></div>`
    : '';

  // Parse structured notes sections
  let notesHtml = '';
  if (c.notes) {
    const parsed = parseNotesSections(c.notes);

    const objHtml = parsed.objective
      ? `<div class="notes-objective">
          <div class="notes-section-label">🎯 Objective</div>
          <div class="notes-section-body">${mdToHtml(parsed.objective)}</div>
        </div>`
      : '';

    const dodHtml = parsed.dod
      ? `<div class="notes-dod">
          <div class="notes-section-label">✅ Definition of Done</div>
          <div class="notes-section-body">${mdToHtml(parsed.dod)}</div>
        </div>`
      : '';

    const srcRefHtml = parsed.sourceRef
      ? `<div class="notes-source-ref">
          <span style="color:var(--text-subtle)">Source ref:</span>
          <span class="pill pl-source" title="${esc(parsed.sourceRef)}">${esc(parsed.sourceRef)}</span>
        </div>`
      : '';

    notesHtml = `<div class="panel-section" style="border-top:none;padding-top:0;margin-top:0">
      <div class="panel-sec-title">📝 Notes</div>
      ${objHtml}
      ${dodHtml}
      ${srcRefHtml}
      <div class="md-body">${mdToHtml(c.notes)}</div>
    </div>`;
  }

  // Completion Summary — shown for done/review cards
  let completionHtml = '';
  if (c.status === 'done' || c.status === 'review') {
    const completedComment = (c.comments||[]).find(cm => (cm.body||'').trim().toLowerCase().startsWith('completed:'));
    if (completedComment) {
      completionHtml = `<div class="panel-section" style="border-top:none;padding-top:0;margin-top:0">
        <div class="panel-sec-title">🏁 Completion Summary</div>
        <div class="completion-summary">
          <div class="notes-section-body">${mdToHtml(completedComment.body)}</div>
        </div>
      </div>`;
    } else if ((c.proof||[]).length > 0) {
      completionHtml = `<div class="panel-section" style="border-top:none;padding-top:0;margin-top:0">
        <div class="panel-sec-title">🏁 Completion Summary</div>
        <div class="completion-summary">
          <div class="notes-section-body" style="color:var(--text-muted);font-style:italic">Proof submitted but no summary recorded.</div>
        </div>
      </div>`;
    }
  }

  const childrenHtml = (c.children||[]).length > 0
    ? `<div class="panel-section">
        <div class="panel-sec-title">📌 Sub-cards (${c.children.length})</div>
        ${(c.children||[]).map(ch =>
          `<div class="subcard-item" onclick="openCard('${esc(ch.id)}')">
            ${statusPill(ch.status)}
            <span style="font-size:12px">${esc(ch.title)}</span>
          </div>`
        ).join('')}
       </div>`
    : '';

  const tlDotClass = kind => {
    const m = {created:'dk-created', claimed:'dk-claimed', claim_acquired:'dk-claimed',
                completed:'dk-completed', done:'dk-done', failed:'dk-failed',
                blocked:'dk-blocked', status_changed:'dk-status_changed',
                status_change:'dk-status_change', started:'dk-started'};
    return m[kind] || '';
  };

  const eventsHtml = (c.events||[]).length > 0
    ? `<div class="panel-section">
        <div class="panel-sec-title">🕐 Timeline (${c.events.length})</div>
        <div class="timeline">
          ${(c.events||[]).map(e =>
            `<div class="tl-item">
              <div class="tl-dot ${tlDotClass(e.kind)}"></div>
              <div class="tl-body">
                <div class="tl-kind">${esc((e.kind||'').replace(/_/g,' '))}</div>
                ${e.from_status && e.to_status
                  ? `<div class="tl-sub">${esc(e.from_status)} → ${esc(e.to_status)}</div>`
                  : ''}
              </div>
              <div class="tl-time" title="${e.at ? new Date(e.at).toLocaleString() : ''}">${reltime(e.at)}</div>
            </div>`
          ).join('')}
        </div>
       </div>`
    : '';

  const attemptsHtml = (c.attempts||[]).length > 0
    ? `<div class="panel-section">
        <div class="panel-sec-title">🤖 Execution (${c.attempts.length} attempt${c.attempts.length!==1?'s':''})</div>
        ${(c.attempts||[]).map(a =>
          `<div class="attempt-item">
            <div class="attempt-hdr">
              ${statusPill(a.status)}
              ${a.model ? `<span style="font-size:11px;color:var(--text-muted)">${esc(a.model)}</span>` : ''}
              ${a.started_at && a.ended_at
                ? `<span style="font-size:11px;color:var(--text-subtle);margin-left:auto">${fmtDuration(a.started_at,a.ended_at)}</span>`
                : ''}
            </div>
            <div class="attempt-detail">
              ${a.engine ? `Engine: ${esc(a.engine)}` : ''}
              ${a.mode ? ` · Mode: ${esc(a.mode)}` : ''}
              ${a.started_at ? ` · ${fmtDateSmart(a.started_at)}` : ''}
            </div>
            ${a.error ? `<div class="attempt-error">${esc((a.error||'').slice(0,500))}</div>` : ''}
          </div>`
        ).join('')}
       </div>`
    : '';

  const logsHtml = (c.logs||[]).length > 0
    ? `<div class="panel-section">
        <div class="panel-sec-title">📟 Worker Logs (${c.logs.length})</div>
        <div class="log-list">
          ${(c.logs||[]).map(l =>
            `<div class="log-item">
              <span class="log-time">${fmtDateSmart(l.created_at)}</span>
              <span class="ll-${l.level||'info'}">${esc(l.message)}</span>
            </div>`
          ).join('')}
        </div>
       </div>`
    : '';

  const proofIco = s => s==='pass'?'✅':s==='fail'?'❌':'⏭️';
  const proofHtml = (c.proof||[]).length > 0
    ? `<div class="panel-section">
        <div class="panel-sec-title">✅ Proof (${c.proof.length})</div>
        ${(c.proof||[]).map(p =>
          `<div class="proof-item">
            <span class="proof-ico">${proofIco(p.status)}</span>
            <div class="proof-body">
              ${p.label ? `<div class="proof-label">${esc(p.label)}</div>` : ''}
              ${p.command ? `<span class="proof-cmd">${esc(p.command)}</span>` : ''}
              ${p.note ? `<div class="proof-note">${esc(p.note)}</div>` : ''}
            </div>
          </div>`
        ).join('')}
       </div>`
    : '';

  const commentsHtml = (c.comments||[]).length > 0
    ? `<div class="panel-section">
        <div class="panel-sec-title">💬 Comments (${c.comments.length})</div>
        ${(c.comments||[]).map(cm =>
          `<div class="comment-item">
            <div>${esc(cm.body)}</div>
            <div class="comment-time">${fmtDateSmart(cm.created_at)}</div>
          </div>`
        ).join('')}
       </div>`
    : '';

  const attachHtml = (c.attachments||[]).length > 0
    ? `<div class="panel-section">
        <div class="panel-sec-title">📎 Attachments (${c.attachments.length})</div>
        ${(c.attachments||[]).map(a =>
          `<div class="attach-item">
            <span class="attach-icon">${attachIcon(a.mime_type)}</span>
            <div>
              <div class="attach-name">${esc(a.file_name)}</div>
              <div class="attach-meta">${fmtBytes(a.byte_size)}${a.mime_type?' · '+esc(a.mime_type):''}</div>
              ${a.note ? `<div class="attach-note">${esc(a.note)}</div>` : ''}
            </div>
          </div>`
        ).join('')}
       </div>`
    : '';

  const panelDeleteTitle = esc(c.title).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
  const deleteBtn = `<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">
    <button onclick="promptDelete(event,'${esc(c.id)}','${panelDeleteTitle}')" style="
      background:rgba(248,81,73,0.08);border:1px solid rgba(248,81,73,0.25);color:var(--red);
      border-radius:6px;padding:7px 14px;font-size:12px;font-weight:500;cursor:pointer;
      display:flex;align-items:center;gap:5px;transition:all 0.15s;
    " onmouseover="this.style.background='rgba(248,81,73,0.15)'" onmouseout="this.style.background='rgba(248,81,73,0.08)'">🗑 Archive this card</button>
  </div>`;

  return `
    <div class="panel-title">${esc(c.title)}</div>
    ${metaGrid}
    ${costBreakdownHtml(c)}
    ${labelsHtml}
    ${srcHtml}
    ${notesHtml}
    ${completionHtml}
    ${childrenHtml}
    ${eventsHtml}
    ${attemptsHtml}
    ${logsHtml}
    ${proofHtml}
    ${commentsHtml}
    ${attachHtml}
    ${deleteBtn}
  `;
}

// ── Panel: Wiki Page Detail ────────────────────────────────

function encodePageId(p) {
  return (CWS + '-' + p.path).replace(/[/\\.]/g, '-');
}

function openPage(pageId) {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const page = (ws.pages||[]).find(p => encodePageId(p) === pageId);
  if (!page) return;
  document.getElementById('panel-hdr-label').textContent = page.pageType || 'Page';
  document.getElementById('panel-body').innerHTML = pagePanelHtml(page);
  openPanel();
}

function pagePanelHtml(p) {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const isSource = p.folder === 'sources';

  // Find wikilinks in body and try to resolve them
  const linkedPages = [];
  if (p.body) {
    const wlMatches = [...(p.body.matchAll(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g))];
    const wlNames = wlMatches.map(m => m[1].trim().toLowerCase());
    if (wlNames.length > 0) {
      for (const pg of (ws.pages||[])) {
        const pgTitle = (pg.title||'').toLowerCase();
        const pgStem = (pg.path||'').split('/').pop().replace(/\.md$/,'').replace(/-/g,' ').toLowerCase();
        if (wlNames.some(wl => wl === pgTitle || wl === pgStem) && pg.path !== p.path) {
          linkedPages.push(pg);
        }
      }
    }
  }

  const linkedHtml = linkedPages.length > 0
    ? `<div class="panel-section">
        <div class="panel-sec-title">🔗 Linked Pages (${linkedPages.length})</div>
        ${linkedPages.map(lp =>
          `<div class="subcard-item" onclick="openPage('${esc(encodePageId(lp))}')">
            <span class="badge badge-${esc(lp.pageType||'unknown')}" style="font-size:10px">${esc(lp.pageType||'?')}</span>
            <span style="font-size:12px">${esc(lp.title)}</span>
          </div>`
        ).join('')}
       </div>`
    : '';

  // Format date smartly if it's a timestamp, else show as-is
  let displayDate = '';
  if (p.updatedAt) {
    const d = new Date(p.updatedAt);
    displayDate = isNaN(d.getTime()) ? p.updatedAt.slice(0,10) : fmtDateSmart(d.getTime());
  }

  return `
    <div class="panel-title">${esc(p.title)}</div>
    <div style="margin-bottom:12px;display:flex;align-items:center;gap:6px;flex-wrap:wrap">
      <span class="badge badge-${esc(p.pageType||'unknown')}">${esc(p.pageType||'?')}</span>
      ${p.folder && p.folder !== 'root' ? `<span class="badge badge-muted">${esc(p.folder)}</span>` : ''}
      ${p.status ? `<span class="badge badge-muted">${esc(p.status)}</span>` : ''}
      ${p.entityType ? `<span class="badge badge-muted">${esc(p.entityType)}</span>` : ''}
      ${displayDate ? `<span style="font-size:11px;color:var(--text-muted);margin-left:auto">${esc(displayDate)}</span>` : ''}
    </div>
    <div class="md-body">${mdToHtml(p.body||'')}</div>
    ${p.bodyTruncated ? '<div style="margin:12px 0;padding:8px 12px;background:var(--bg-hover);border-radius:6px;font-size:12px;color:var(--text-muted)">Content truncated at 32K chars. Full content in wiki file.</div>' : ''}
    ${linkedHtml}
    <div style="margin-top:16px;padding-top:10px;border-top:1px solid var(--border);font-size:11px;color:var(--text-subtle);font-family:monospace">${esc(p.path)}</div>
  `;
}

// ── Panel open/close ───────────────────────────────────────

function openPanel() {
  document.getElementById('panel-backdrop').classList.add('open');
  document.getElementById('detail-panel').classList.add('open');
  // Scroll panel body to top
  requestAnimationFrame(() => {
    const pb = document.getElementById('panel-body');
    if (pb) pb.scrollTop = 0;
  });
}
function closePanel() {
  document.getElementById('panel-backdrop').classList.remove('open');
  document.getElementById('detail-panel').classList.remove('open');
}

// ── Shortcuts overlay ──────────────────────────────────────

function openShortcuts() {
  document.getElementById('shortcuts-overlay').classList.add('open');
}
function closeShortcuts() {
  document.getElementById('shortcuts-overlay').classList.remove('open');
}

// ── Keyboard shortcuts ─────────────────────────────────────

document.addEventListener('keydown', e => {
  // Ignore when typing in inputs
  const tag = (e.target.tagName||'').toLowerCase();
  const inInput = tag === 'input' || tag === 'textarea' || tag === 'select';

  if (e.key === 'Escape') {
    if (document.getElementById('confirm-overlay').classList.contains('open')) {
      cancelConfirm(); return;
    }
    if (document.getElementById('shortcuts-overlay').classList.contains('open')) {
      closeShortcuts(); return;
    }
    closePanel();
    return;
  }

  if (inInput) return;

  if (e.key === '?') {
    e.preventDefault();
    openShortcuts();
    return;
  }
  if (e.key === '/') {
    e.preventDefault();
    // Focus the visible search input
    const search = document.querySelector('.search-input');
    if (search) search.focus();
    return;
  }
  if (e.key === '1') { switchTab('work'); return; }
  if (e.key === '2') { switchTab('knowledge'); return; }
  if (e.key === '3') { switchTab('sources'); return; }
  if (e.key === '4') { switchTab('activity'); return; }
});

// ── Activity Tab ─────────────────────────────────────────

let ACT_WS_FILTER = 'all';   // activity: workspace filter
let ACT_KIND_FILTER = 'all'; // activity: event kind filter
let ACT_SEARCH = '';          // activity: card title search
let _expandedLogs = {};       // card id → bool

function relTime(ms) {
  const diff = Date.now() - ms;
  if (diff < 60000) return Math.floor(diff/1000) + 's ago';
  if (diff < 3600000) return Math.floor(diff/60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff/3600000) + 'h ago';
  const d = Math.floor(diff/86400000);
  return d === 1 ? '1d ago' : d + 'd ago';
}

function eventIcon(kind, fromStatus, toStatus) {
  if (kind === 'created') return '📌';
  if (kind === 'dispatch') return '🚀';
  if (kind === 'claimed' || kind === 'claim_acquired') return '🔄';
  if (kind === 'moved' || kind === 'status_change' || kind === 'status_changed') {
    const to = toStatus || '';
    if (to === 'running') return '🏃';
    if (to === 'done') return '✅';
    if (to === 'blocked') return '🚫';
    if (to === 'review') return '👀';
    if (to === 'ready') return '✅';
    if (to === 'scheduled') return '📅';
    return '🔄';
  }
  if (kind === 'attempt_updated') return '⚡';
  if (kind === 'orchestration') return '🧭';
  if (kind === 'linked') return '🔗';
  if (kind === 'completed') return '✅';
  if (kind === 'failed') return '❌';
  return '●';
}

function wsBadgeClass(wsId) {
  const id = (wsId||'').toLowerCase();
  if (id === 'heimdall') return 'ws-heimdall';
  if (id === 'slate') return 'ws-slate';
  if (id === 'laurion') return 'ws-laurion';
  return 'ws-default';
}

function toggleLogs(cardId) {
  _expandedLogs[cardId] = !_expandedLogs[cardId];
  const body = document.getElementById('logs-' + cardId);
  if (body) body.classList.toggle('open', !!_expandedLogs[cardId]);
  const btn = document.getElementById('logtoggle-' + cardId);
  if (btn) btn.textContent = _expandedLogs[cardId] ? '▼ Hide logs' : '▶ ' + btn.dataset.count + ' log entries';
}

function renderActivity() {
  const allWs = window.FOUNDRY_DATA.workspaces;

  // Collect all events from all workspaces
  const events = [];
  const cardMap = {}; // cardId → card+wsId
  for (const [wsId, ws] of Object.entries(allWs)) {
    for (const card of (ws.cards||[])) {
      cardMap[card.id] = { ...card, wsId, wsName: ws.name };
      for (const ev of (card.events||[])) {
        events.push({
          ...ev,
          cardId: card.id,
          cardTitle: card.title,
          cardStatus: card.status,
          agentId: card.agent_id,
          wsId,
          wsName: ws.name,
          logs: card.logs || [],
        });
      }
    }
  }

  // Sort newest first
  events.sort((a, b) => (b.at||0) - (a.at||0));

  // Stats: compute against ALL events (before filter)
  const now = Date.now();
  const dayStart = new Date(); dayStart.setHours(0,0,0,0);
  const todayTs = dayStart.getTime();
  const eventsToday = events.filter(e => (e.at||0) >= todayTs).length;

  // Cards running now (across all workspaces)
  const allCards = Object.values(allWs).flatMap(w => w.cards||[]);
  const runningNow = allCards.filter(c => c.status === 'running').length;
  const doneToday = allCards.filter(c => c.status === 'done' && (c.completed_at||0) >= todayTs).length;
  const blockedNow = allCards.filter(c => c.status === 'blocked').length;

  // Get unique workspaces and kinds for filter dropdowns
  const wsIds = [...new Set(events.map(e => e.wsId))];
  const kinds = [...new Set(events.map(e => e.kind))].sort();

  // Apply filters
  let filtered = events;
  if (ACT_WS_FILTER !== 'all') filtered = filtered.filter(e => e.wsId === ACT_WS_FILTER);
  if (ACT_KIND_FILTER !== 'all') filtered = filtered.filter(e => e.kind === ACT_KIND_FILTER);
  if (ACT_SEARCH) {
    const q = ACT_SEARCH.toLowerCase();
    filtered = filtered.filter(e => (e.cardTitle||'').toLowerCase().includes(q));
  }

  // Stats HTML
  const statsHtml = `<div class="activity-stats">
    <div class="stat-card ${eventsToday>0?'has-value':''}">
      <div class="stat-value ${eventsToday>0?'c-accent':''}">${eventsToday}</div>
      <div class="stat-label">Events Today</div>
    </div>
    <div class="stat-card ${runningNow>0?'has-value':''}">
      <div class="stat-value ${runningNow>0?'c-accent':''}">${runningNow}</div>
      <div class="stat-label">Running Now</div>
    </div>
    <div class="stat-card ${doneToday>0?'has-value c-green':''}">
      <div class="stat-value ${doneToday>0?'c-green':''}">${doneToday}</div>
      <div class="stat-label">Done Today</div>
    </div>
    <div class="stat-card ${blockedNow>0?'has-value c-red':''}">
      <div class="stat-value ${blockedNow>0?'c-red':''}">${blockedNow}</div>
      <div class="stat-label">Blocked</div>
    </div>
  </div>`;

  // Filter bar
  const wsOptions = wsIds.map(id => `<option value="${esc(id)}" ${ACT_WS_FILTER===id?'selected':''}>${esc(allWs[id]?.name||id)}</option>`).join('');
  const kindOptions = kinds.map(k => `<option value="${esc(k)}" ${ACT_KIND_FILTER===k?'selected':''}>${esc(k)}</option>`).join('');
  const filterBar = `<div class="activity-filter-bar">
    <select class="activity-filter-select" onchange="ACT_WS_FILTER=this.value;renderActivity()">
      <option value="all" ${ACT_WS_FILTER==='all'?'selected':''}>All workspaces</option>
      ${wsOptions}
    </select>
    <select class="activity-filter-select" onchange="ACT_KIND_FILTER=this.value;renderActivity()">
      <option value="all" ${ACT_KIND_FILTER==='all'?'selected':''}>All event types</option>
      ${kindOptions}
    </select>
    <div class="search-wrap" style="flex:1;min-width:160px">
      <span class="search-icon">🔍</span>
      <input class="search-input" type="search" placeholder="Filter by card title…"
        value="${esc(ACT_SEARCH)}" oninput="ACT_SEARCH=this.value;renderActivity()">
    </div>
    <span style="color:var(--text-muted);font-size:11px;white-space:nowrap">${filtered.length} event${filtered.length!==1?'s':''}</span>
  </div>`;

  // Timeline rows
  let rows = '';
  if (filtered.length === 0) {
    rows = `<div class="activity-empty">⚡ No events match the current filter.</div>`;
  } else {
    // Track which cards we've already rendered logs for (only once per card, after first event)
    const logCardsSeen = new Set();
    for (const ev of filtered.slice(0, 300)) {
      const icon = eventIcon(ev.kind, ev.from_status, ev.to_status);
      const tsStr = ev.at ? relTime(ev.at) : '';
      const ts2 = ev.at ? new Date(ev.at).toLocaleTimeString('en-AU',{hour:'2-digit',minute:'2-digit',hour12:false}) : '';
      const wsClass = wsBadgeClass(ev.wsId);

      let transitionHtml = '';
      if (ev.from_status && ev.to_status) {
        transitionHtml = `<span class="transition-badge">${esc(ev.from_status)} → ${esc(ev.to_status)}</span>`;
      } else if (ev.to_status) {
        transitionHtml = `<span class="transition-badge">→ ${esc(ev.to_status)}</span>`;
      } else if (ev.from_status) {
        transitionHtml = `<span class="transition-badge">${esc(ev.from_status)} →</span>`;
      }

      let agentHtml = '';
      if (ev.agentId) {
        agentHtml = `<span class="agent-badge">${esc(ev.agentId)}</span>`;
      }

      // Logs for this card (shown once, under the first event per card)
      let logHtml = '';
      if (ev.logs && ev.logs.length > 0 && !logCardsSeen.has(ev.cardId)) {
        logCardsSeen.add(ev.cardId);
        const logLines = ev.logs.map(l => {
          const lt = l.created_at ? new Date(l.created_at).toLocaleTimeString('en-AU',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}) : '';
          return `<div class="activity-log-line"><span class="log-ts">${esc(lt)}</span><span class="log-msg">${esc(l.message||'')}</span></div>`;
        }).join('');
        logHtml = `<div style="grid-column:1/-1;padding:4px 12px 6px 52px">
          <button class="log-toggle-btn" id="logtoggle-${esc(ev.cardId)}" data-count="${ev.logs.length}" onclick="toggleLogs('${esc(ev.cardId)}')">▶ ${ev.logs.length} log entr${ev.logs.length===1?'y':'ies'}</button>
          <div class="activity-log-body" id="logs-${esc(ev.cardId)}">${logLines}</div>
        </div>`;
      }

      rows += `<div class="activity-row">
        <span class="activity-ts" title="${ts2}">${esc(tsStr)}</span>
        <span class="activity-icon">${icon}</span>
        <div class="activity-body">
          <span class="activity-card-title" title="${esc(ev.cardTitle||'')}">${esc(ev.cardTitle||'(untitled)')}</span>
          <div class="activity-meta">
            <span style="font-size:10px;color:var(--text-muted);text-transform:capitalize">${esc(ev.kind)}</span>
            ${transitionHtml}
          </div>
        </div>
        <div class="activity-badges">
          ${agentHtml}
          <span class="ws-badge ${wsClass}">${esc(ev.wsName||ev.wsId)}</span>
        </div>
      </div>${logHtml}`;
    }
  }

  const mc = document.getElementById('main-content');
  mc.innerHTML = statsHtml + filterBar + `<div class="activity-feed">${rows}</div>`;
}

// ── Filter handlers ────────────────────────────────────────

function setStatus(s) { F_STATUS = s; renderWork(); }
function setPrio(v) { F_PRIO = v; renderWork(); }
function setAgent(v) { F_AGENT = v; renderWork(); }
function debSearch(v) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { F_SEARCH = v; renderWork(); }, 180);
}
function debWiki(v) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { F_WIKI = v; renderKnowledge(); }, 180);
}
function debSource(v) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { F_SOURCE_SEARCH = v; renderSources(); }, 180);
}
function setFolder(f) { F_FOLDER = f; F_DECISION = false; renderKnowledge(); }
function setWikiType(t) { F_WIKI_TYPE = t; renderKnowledge(); }
function toggleDecision() { F_DECISION = !F_DECISION; F_FOLDER = 'all'; renderKnowledge(); }

// ── Drag & Drop ─────────────────────────────────────────────

let _dragCardId = null;

function onDragStart(e, cardId) {
  _dragCardId = cardId;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', cardId);
  requestAnimationFrame(() => e.target.classList.add('dragging'));
}

function onDragEnd(e) {
  e.target.classList.remove('dragging');
  _dragCardId = null;
  // Clean up all drag-over states
  document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
  document.querySelectorAll('.drag-target').forEach(el => el.classList.remove('drag-target'));
}

function onColDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const body = e.currentTarget.querySelector('.kanban-col-body');
  if (body) body.classList.add('drag-over');
  e.currentTarget.classList.add('drag-target');
}

function onColDragLeave(e) {
  // Only remove if leaving the column entirely
  if (!e.currentTarget.contains(e.relatedTarget)) {
    const body = e.currentTarget.querySelector('.kanban-col-body');
    if (body) body.classList.remove('drag-over');
    e.currentTarget.classList.remove('drag-target');
  }
}

async function onColDrop(e, newStatus) {
  e.preventDefault();
  const cardId = e.dataTransfer.getData('text/plain') || _dragCardId;
  if (!cardId) return;
  // Clean up visual state
  document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
  document.querySelectorAll('.drag-target').forEach(el => el.classList.remove('drag-target'));

  // Find card's current status
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const card = (ws.cards||[]).find(c => c.id === cardId);
  if (!card || card.status === newStatus) return;

  const oldStatus = card.status;
  // Optimistic update
  card.status = newStatus;
  card.updated_at = new Date().toISOString();
  renderWork();

  try {
    const resp = await fetch(`/api/cards/${encodeURIComponent(cardId)}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }
    // Force data refresh on next cycle
    refreshData();
  } catch (err) {
    // Revert on failure
    card.status = oldStatus;
    renderWork();
    alert('Failed to update status: ' + err.message);
  }
}

// ── Dispatch ────────────────────────────────────────────────

function showToast(msg, type='info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast t-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

async function dispatchAll() {
  const btn = document.querySelector('.dispatch-btn');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('loading');
  const origText = btn.textContent;
  btn.textContent = '⏳ Dispatching…';
  try {
    const resp = await fetch('/api/dispatch', { method: 'POST' });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    const summary = data.started ? `Started ${data.started} card(s)` :
      data.output ? data.output : 'Dispatch complete';
    showToast(summary, 'success');
    await refreshData();
  } catch (err) {
    showToast('Dispatch failed: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
    btn.textContent = origText;
  }
}

async function dispatchCard(event, cardId) {
  event.stopPropagation();
  const btn = event.currentTarget;
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = '⏳';
  try {
    const resp = await fetch(`/api/cards/${encodeURIComponent(cardId)}/start`, { method: 'POST' });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    showToast('Dispatch complete', 'success');
    await refreshData();
  } catch (err) {
    showToast('Start failed: ' + err.message, 'error');
    btn.disabled = false;
    btn.textContent = '▶';
  }
}

// ── Delete / Archive ────────────────────────────────────────

let _pendingDeleteId = null;
let _pendingDeleteTitle = null;

function promptDelete(e, cardId, title) {
  e.stopPropagation();
  _pendingDeleteId = cardId;
  _pendingDeleteTitle = title;
  document.getElementById('confirm-msg').textContent =
    `Archive "${title}"? It will be removed from the board.`;
  document.getElementById('confirm-overlay').classList.add('open');
}

function cancelConfirm() {
  _pendingDeleteId = null;
  _pendingDeleteTitle = null;
  document.getElementById('confirm-overlay').classList.remove('open');
}

async function execConfirm() {
  const cardId = _pendingDeleteId;
  if (!cardId) return;
  cancelConfirm();

  // Optimistic: remove from local data
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const idx = (ws.cards||[]).findIndex(c => c.id === cardId);
  let removed = null;
  if (idx >= 0) {
    removed = ws.cards.splice(idx, 1)[0];
  }
  renderWork();
  // Also close panel if this card was open
  closePanel();

  try {
    const resp = await fetch(`/api/cards/${encodeURIComponent(cardId)}`, {
      method: 'DELETE',
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }
    refreshData();
  } catch (err) {
    // Revert
    if (removed && ws.cards) {
      ws.cards.splice(idx, 0, removed);
      renderWork();
    }
    alert('Failed to archive card: ' + err.message);
  }
}

// ── Theme ──────────────────────────────────────────────────
function applyTheme(theme) {
  if (theme === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
    document.getElementById('theme-icon').textContent = '☀️';
  } else {
    document.documentElement.removeAttribute('data-theme');
    document.getElementById('theme-icon').textContent = '🌙';
  }
}
function toggleTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const next = isDark ? 'light' : 'dark';
  localStorage.setItem('foundry-theme', next);
  applyTheme(next);
}
// Apply saved theme (default: light)
applyTheme(localStorage.getItem('foundry-theme') || 'light');

// ── Boot ───────────────────────────────────────────────────
initApp();
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────
#  Final HTML generator
# ─────────────────────────────────────────────

def generate_html(data):
    json_str = json.dumps(data, ensure_ascii=False, default=str)
    json_str = json_str.replace("</", "<\\/").replace("<!--", "<\\!--")

    ws_options = []
    for i, (ws_id, ws) in enumerate(data["workspaces"].items()):
        active = " active" if i == 0 else ""
        name = html_mod.escape(ws["name"])
        wid = html_mod.escape(ws_id)
        ws_options.append(
            f'<button class="ws-btn{active}" data-ws="{wid}" '
            f'onclick="switchWs(\'{wid}\', this)">{name}</button>'
        )
    ws_options_html = "\n  ".join(ws_options)
    build_ts = datetime.now().strftime("%d %b %Y %H:%M")

    out = HTML_TEMPLATE
    out = out.replace("__FOUNDRY_DATA__", json_str)
    out = out.replace("__WS_OPTIONS__", ws_options_html)
    out = out.replace("__BUILD_TS__", build_ts)
    return out


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Foundry Dashboard Generator v4")
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
    parser.add_argument("--out", default="./dist/index.html")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    data = build_foundry_data(manifest, args.db)

    html_content = generate_html(data)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_content)
    print(f"\nDashboard written to {out_path} ({len(html_content):,} bytes)")


if __name__ == "__main__":
    main()
