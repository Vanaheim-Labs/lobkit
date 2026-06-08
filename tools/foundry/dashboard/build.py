#!/usr/bin/env python3
"""
Foundry Dashboard — Rich Static Site Generator v3

Reads the wiki vault + workboard SQLite and generates a self-contained
HTML dashboard with a Workboard-quality UI.

Features:
- Right-side slide-out detail panel (440px)
- Full card data: events timeline, execution attempts, worker logs,
  proof, comments, attachments, sub-cards
- Client-side search and multi-filter (status, priority, agent, text)
- Pulsing running cards, colored priority/status/agent badges
- Wiki knowledge slide-out panel with search
- Multi-workspace support via manifest.json
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
            "body": body[:5000],
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
:root {
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
  --panel-width: 440px;
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
.ws-btn.active { background: var(--accent); color: #000; border-color: var(--accent); font-weight: 600; }

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

/* Card list */
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
.card-item:hover { border-color: var(--accent); border-left-color: var(--accent); box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
.card-item.s-running { border-left-color: var(--accent); animation: pulseLeft 2.2s ease-in-out infinite; }
.card-item.s-blocked { border-left-color: var(--red); }
.card-item.s-done { border-left-color: var(--green); opacity: 0.72; }
.card-item.s-ready { border-left-color: var(--green); }
.card-item.s-review { border-left-color: var(--orange); }
.card-item.s-todo { border-left-color: var(--text-subtle); }
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

/* Slide-out panel */
.panel-backdrop {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
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
.wiki-card-meta { font-size: 11px; color: var(--text-muted); }

/* Sources */
.source-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 13px 16px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.source-item:hover { border-color: var(--accent); }
.source-item h3 { font-size: 14px; margin-bottom: 3px; }
.source-meta { font-size: 11px; color: var(--text-muted); }

.footer-note { text-align: center; color: var(--text-subtle); font-size: 11px; padding: 28px 0 16px; }

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

<div class="footer-note" id="footer-note">Generated __BUILD_TS__ · Foundry v3</div>

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

// Simple markdown → HTML
function mdToHtml(text) {
  if (!text) return '';
  let t = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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
  const out = []; let inUl = false, inOl = false;
  for (const line of lines) {
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
  const L = {running:'🔨 Running', blocked:'🚫 Blocked', done:'✅ Done', ready:'🟢 Ready', review:'👀 Review', todo:'📋 Todo'};
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

let CWS = null;        // current workspace id
let CTAB = 'work';     // current inner tab
let F_STATUS = 'all';  // status filter
let F_PRIO = 'all';    // priority filter
let F_AGENT = 'all';   // agent filter
let F_SEARCH = '';     // card search
let F_WIKI = '';       // wiki search
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
    </nav>`;

  if (CTAB === 'work') renderWork();
  else if (CTAB === 'knowledge') renderKnowledge();
  else renderSources();
}

// ── Work Tab ───────────────────────────────────────────────

function renderWork() {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const all = ws.cards || [];

  const byStatus = s => all.filter(c => c.status === s).length;
  const running = byStatus('running'), blocked = byStatus('blocked'), done = byStatus('done');
  const active = all.filter(c => c.status !== 'done').length;

  const agents = [...new Set(all.map(c => c.agent_id).filter(Boolean))].sort();

  // Apply filters
  let cards = all;
  if (F_STATUS !== 'all') cards = cards.filter(c => c.status === F_STATUS);
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
        <input class="search-input" type="search" placeholder="Search cards…"
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
    </div>
    <div class="status-filters">
      ${['all','running','blocked','review','ready','todo','done'].map(s => {
        const cnt = s === 'all' ? all.length : byStatus(s);
        return `<button class="sf-btn ${F_STATUS===s?'active':''}" data-s="${s}"
          onclick="setStatus('${s}')">${s==='all'?'All':s.charAt(0).toUpperCase()+s.slice(1)}
          ${s!=='all'?`<span style="opacity:.65">(${cnt})</span>`:''}</button>`;
      }).join('')}
    </div>`;

  const cardsHtml = cards.length === 0
    ? `<div class="empty-state"><div class="empty-icon">📋</div><p>No cards match the current filters.</p></div>`
    : `<div class="card-list">${cards.map(c => cardItemHtml(c)).join('')}</div>`;

  document.getElementById('main-content').innerHTML = statsHtml + controlsHtml + cardsHtml;
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

// ── Knowledge Tab ──────────────────────────────────────────

function renderKnowledge() {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const all = (ws.pages||[]).filter(p => p.folder !== 'sources');

  let pages = all;
  if (F_WIKI) {
    const q = F_WIKI.toLowerCase();
    pages = pages.filter(p =>
      (p.title||'').toLowerCase().includes(q) ||
      (p.body||'').toLowerCase().includes(q) ||
      (p.entityType||'').toLowerCase().includes(q)
    );
  }

  const cnt = f => all.filter(p => p.folder === f).length;

  const kStat = (val, label, cls='') => {
    const hv = val > 0 ? `has-value ${cls}` : '';
    const vc = val > 0 && cls ? `c-${cls}` : (val > 0 ? 'c-accent' : '');
    return `<div class="stat-card ${hv}"><div class="stat-value ${vc}">${val}</div><div class="stat-label">${label}</div></div>`;
  };
  const statsHtml = `<div class="stats-grid">
    ${kStat(cnt('entities'), 'Entities')}
    ${kStat(cnt('concepts'), 'Concepts', 'orange')}
    ${kStat(cnt('syntheses'), 'Syntheses', 'green')}
    ${kStat(all.length, 'Total Pages')}
  </div>`;

  const searchHtml = `<div class="controls-bar" style="margin-bottom:16px">
    <div class="search-wrap">
      <span class="search-icon">🔍</span>
      <input class="search-input" type="search" placeholder="Search knowledge…"
        value="${esc(F_WIKI)}" oninput="debWiki(this.value)">
    </div>
  </div>`;

  const gridHtml = pages.length === 0
    ? `<div class="empty-state"><div class="empty-icon">📚</div><p>No pages match your search.</p></div>`
    : `<div class="knowledge-grid">${pages.map(p => wikiCardHtml(p)).join('')}</div>`;

  document.getElementById('main-content').innerHTML = statsHtml + searchHtml + gridHtml;
}

function wikiCardHtml(p) {
  const pid = encodePageId(p);
  return `<div class="wiki-card" onclick="openPage('${esc(pid)}')">
    <div>
      <span class="badge badge-${esc(p.pageType||'unknown')}">${esc(p.pageType||'?')}</span>
      ${p.folder && p.folder !== 'root' ? `<span class="badge badge-muted">${esc(p.folder)}</span>` : ''}
      ${p.status ? `<span class="badge badge-muted">${esc(p.status)}</span>` : ''}
    </div>
    <div class="wiki-card-title">${esc(p.title)}</div>
    <div class="wiki-card-meta">${p.entityType ? esc(p.entityType)+' · ' : ''}${p.updatedAt ? esc(p.updatedAt.slice(0,10)) : ''}</div>
  </div>`;
}

// ── Sources Tab ────────────────────────────────────────────

function renderSources() {
  const ws = window.FOUNDRY_DATA.workspaces[CWS];
  const sources = (ws.pages||[]).filter(p => p.folder === 'sources');

  const statsHtml = `<div class="stats-grid">
    <div class="stat-card"><div class="stat-value">${sources.length}</div><div class="stat-label">Committed Sources</div></div>
  </div>`;

  const itemsHtml = sources.length === 0
    ? `<div class="empty-state"><div class="empty-icon">📰</div><p>No sources committed yet.</p></div>`
    : sources.map(s => {
        const pid = encodePageId(s);
        return `<div class="source-item" onclick="openPage('${esc(pid)}')">
          <h3>${esc(s.title)}</h3>
          <div class="source-meta">${s.updatedAt ? esc(s.updatedAt.slice(0,10)) : ''}</div>
        </div>`;
      }).join('');

  document.getElementById('main-content').innerHTML = statsHtml + itemsHtml;
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
    <div><div class="pm-label">Updated</div><div class="pm-value" style="font-size:11px;color:var(--text-muted)">${fmtDateTime(c.updated_at)}</div></div>
    ${c.started_at ? `<div><div class="pm-label">Started</div><div class="pm-value" style="font-size:11px;color:var(--text-muted)">${fmtDateTime(c.started_at)}</div></div>` : ''}
    ${c.completed_at ? `<div><div class="pm-label">Completed</div><div class="pm-value" style="font-size:11px;color:var(--text-muted)">${fmtDateTime(c.completed_at)}</div></div>` : ''}
    <div><div class="pm-label">Card ID</div><div class="pm-value" style="font-family:monospace;font-size:11px;color:var(--text-muted)">${esc(short)}</div></div>
    ${c.failure_count > 0 ? `<div><div class="pm-label">Failures</div><div class="pm-value" style="color:var(--red)">${c.failure_count}</div></div>` : ''}
  </div>`;

  const labelsHtml = (c.labels||[]).length > 0
    ? `<div class="panel-labels" style="margin-bottom:10px">${(c.labels||[]).map(l => labelPill(l)).join('')}</div>`
    : '';

  const srcHtml = c.source_url
    ? `<div style="margin-bottom:10px"><a href="${esc(c.source_url)}" target="_blank" class="pill pl-source">↗ View source</a></div>`
    : '';

  const notesHtml = c.notes
    ? `<div class="panel-section" style="border-top:none;padding-top:0;margin-top:0">
        <div class="panel-sec-title">📝 Notes</div>
        <div class="md-body">${mdToHtml(c.notes)}</div>
       </div>`
    : '';

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
              ${a.started_at ? ` · ${fmtDateTime(a.started_at)}` : ''}
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
              <span class="log-time">${fmtDateTime(l.created_at)}</span>
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
            <div class="comment-time">${fmtDateTime(cm.created_at)}</div>
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

  return `
    <div class="panel-title">${esc(c.title)}</div>
    ${metaGrid}
    ${labelsHtml}
    ${srcHtml}
    ${notesHtml}
    ${childrenHtml}
    ${eventsHtml}
    ${attemptsHtml}
    ${logsHtml}
    ${proofHtml}
    ${commentsHtml}
    ${attachHtml}
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
  return `
    <div class="panel-title">${esc(p.title)}</div>
    <div style="margin-bottom:12px">
      <span class="badge badge-${esc(p.pageType||'unknown')}">${esc(p.pageType||'?')}</span>
      ${p.folder && p.folder !== 'root' ? `<span class="badge badge-muted">${esc(p.folder)}</span>` : ''}
      ${p.status ? `<span class="badge badge-muted">${esc(p.status)}</span>` : ''}
      ${p.entityType ? `<span class="badge badge-muted">${esc(p.entityType)}</span>` : ''}
    </div>
    ${p.updatedAt ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:12px">Updated: ${esc(p.updatedAt.slice(0,10))}</div>` : ''}
    <div class="md-body">${mdToHtml(p.body||'')}</div>
    <div style="margin-top:16px;padding-top:10px;border-top:1px solid var(--border);font-size:11px;color:var(--text-subtle);font-family:monospace">${esc(p.path)}</div>
  `;
}

// ── Panel open/close ───────────────────────────────────────

function openPanel() {
  document.getElementById('panel-backdrop').classList.add('open');
  document.getElementById('detail-panel').classList.add('open');
}
function closePanel() {
  document.getElementById('panel-backdrop').classList.remove('open');
  document.getElementById('detail-panel').classList.remove('open');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

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
    parser = argparse.ArgumentParser(description="Foundry Dashboard Generator v3")
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
