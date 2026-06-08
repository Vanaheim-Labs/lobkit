#!/usr/bin/env python3
"""
Foundry Dashboard — Static Site Generator

Reads the wiki vault + workboard SQLite and generates a self-contained
HTML dashboard deployable to Cloudflare Pages or any static host.

Usage:
    python3 build.py [--vault PATH] [--db PATH] [--out PATH] [--workspace ID]

Defaults:
    --vault ~/.openclaw/wiki/heimdall
    --db ~/.openclaw/plugins/workboard/workboard.sqlite
    --out ./dist/index.html
    --workspace heimdall
"""

import argparse
import html
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def parse_frontmatter(content):
    """Extract YAML-ish frontmatter as a dict."""
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
    """Load all wiki pages from the vault."""
    pages = []
    vault = Path(vault_path)
    for md in vault.rglob("*.md"):
        rel = md.relative_to(vault)
        # Skip system files
        if str(rel).startswith(".openclaw-wiki") or str(rel).startswith("_"):
            continue
        if rel.name in ("AGENTS.md", "WIKI.md", "inbox.md"):
            continue
        # Skip index files
        if rel.name == "index.md":
            continue

        content = md.read_text(errors="replace")
        fm, body = parse_frontmatter(content)

        page_type = fm.get("pageType", "unknown")
        folder = str(rel.parent)
        if folder == ".":
            folder = "root"

        pages.append({
            "path": str(rel),
            "folder": folder,
            "pageType": page_type,
            "title": fm.get("title", rel.stem.replace("-", " ").title()),
            "status": fm.get("status", ""),
            "updatedAt": fm.get("updatedAt", ""),
            "body": body,
            "entityType": fm.get("entityType", ""),
        })
    return pages


def load_workboard_cards(db_path, board_id):
    """Load cards from workboard SQLite."""
    cards = []
    if not os.path.exists(db_path):
        return cards

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """SELECT id, title, notes, status, priority, agent_id, 
                  board_id, created_at, updated_at
           FROM workboard_cards 
           WHERE board_id = ? 
           ORDER BY 
             CASE status 
               WHEN 'running' THEN 1 
               WHEN 'blocked' THEN 2
               WHEN 'ready' THEN 3
               WHEN 'todo' THEN 4
               WHEN 'review' THEN 5
               WHEN 'done' THEN 6
             END,
             created_at DESC""",
        (board_id,),
    )
    for row in cursor:
        cards.append(dict(row))
    conn.close()
    return cards


def load_card_links(db_path, board_id):
    """Load parent/child links. child_of links: card_id=child, target_card_id=parent."""
    links = {}
    if not os.path.exists(db_path):
        return links

    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """SELECT l.target_card_id, l.card_id, l.type, c.title
           FROM workboard_card_links l
           JOIN workboard_cards c ON l.card_id = c.id
           WHERE c.board_id = ? AND l.type = 'child_of'""",
        (board_id,),
    )
    for row in cursor:
        parent = row[0][:8]  # target_card_id (parent)
        child_id = row[1][:8]  # card_id (child)
        if parent not in links:
            links[parent] = []
        links[parent].append({"child_id": child_id, "title": row[3]})
    conn.close()
    return links


def status_emoji(status):
    return {
        "running": "🔨",
        "blocked": "🚫",
        "ready": "🟢",
        "todo": "📋",
        "review": "👀",
        "done": "✅",
    }.get(status, "❓")


def priority_class(priority):
    return {
        "urgent": "priority-urgent",
        "high": "priority-high",
        "normal": "priority-normal",
        "low": "priority-low",
    }.get(priority, "priority-normal")


def ts_to_date(ts_ms):
    if not ts_ms:
        return ""
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%d %b %Y")
    except (ValueError, OSError):
        return ""


def md_to_html_simple(text):
    """Very simple markdown → HTML for display."""
    text = html.escape(text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Bullets
    lines = []
    in_list = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            lines.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_list:
                lines.append("</ul>")
                in_list = False
            if stripped.startswith("## "):
                lines.append(f"<h3>{stripped[3:]}</h3>")
            elif stripped.startswith("# "):
                lines.append(f"<h2>{stripped[2:]}</h2>")
            elif stripped:
                lines.append(f"<p>{stripped}</p>")
    if in_list:
        lines.append("</ul>")
    return "\n".join(lines)


def build_html(workspace_name, pages, cards, card_links):
    """Generate the full dashboard HTML."""

    # Categorise pages
    sources = [p for p in pages if p["folder"] == "sources"]
    entities = [p for p in pages if p["folder"] == "entities"]
    concepts = [p for p in pages if p["folder"] == "concepts"]
    syntheses = [p for p in pages if p["folder"] == "syntheses"]
    reports = [p for p in pages if p["folder"] == "reports"]
    knowledge_pages = entities + concepts + syntheses

    # Card stats
    active_cards = [c for c in cards if c["status"] not in ("done",)]
    done_cards = [c for c in cards if c["status"] == "done"]
    blocked_cards = [c for c in cards if c["status"] == "blocked"]

    # Build page detail modals content
    page_details = ""
    for p in pages:
        pid = p["path"].replace("/", "-").replace(".", "-")
        body_html = md_to_html_simple(p["body"][:3000])
        page_details += f'''
        <div id="page-{pid}" class="page-detail" style="display:none">
            <div class="detail-header">
                <span class="badge badge-{p['pageType']}">{p['pageType']}</span>
                <span class="badge">{p['folder']}</span>
                {f'<span class="badge badge-status">{p["status"]}</span>' if p["status"] else ''}
            </div>
            <h2>{html.escape(p['title'])}</h2>
            <div class="detail-body">{body_html}</div>
            <div class="detail-meta">Path: {html.escape(p['path'])}</div>
        </div>'''

    # Build cards HTML
    cards_html = ""
    for c in cards:
        cid = c["id"][:8]
        emoji = status_emoji(c["status"])
        pclass = priority_class(c["priority"])
        notes_preview = (c["notes"] or "")[:120]
        if len(c["notes"] or "") > 120:
            notes_preview += "…"
        date = ts_to_date(c["created_at"])

        children_html = ""
        if cid in card_links:
            children_items = "".join(
                f'<li>{ch["title"]} <span class="card-id">({ch["child_id"]})</span></li>'
                for ch in card_links[cid]
            )
            children_html = f'<div class="card-children"><strong>Sub-cards:</strong><ul>{children_items}</ul></div>'

        cards_html += f'''
        <div class="card card-{c['status']} {pclass}" data-status="{c['status']}">
            <div class="card-header">
                <span class="card-status">{emoji} {c['status']}</span>
                <span class="card-id">#{cid}</span>
                <span class="card-priority">{c['priority']}</span>
            </div>
            <h3 class="card-title">{html.escape(c['title'])}</h3>
            <p class="card-notes">{html.escape(notes_preview)}</p>
            {children_html}
            <div class="card-meta">{date}</div>
        </div>'''

    # Build sources HTML
    sources_html = ""
    for s in sources:
        sid = s["path"].replace("/", "-").replace(".", "-")
        sources_html += f'''
        <div class="source-item" onclick="showPage('page-{sid}')">
            <h3>{html.escape(s['title'])}</h3>
            <div class="source-meta">{html.escape(s.get('updatedAt', '')[:10])}</div>
        </div>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Foundry — {html.escape(workspace_name)}</title>
<style>
:root {{
    --bg: #0d1117; --surface: #161b22; --surface2: #21262d;
    --border: #30363d; --text: #e6edf3; --text-muted: #8b949e;
    --accent: #58a6ff; --green: #3fb950; --red: #f85149;
    --orange: #d29922; --purple: #bc8cff;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); }}
.header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; gap: 16px; }}
.header h1 {{ font-size: 20px; font-weight: 600; }}
.header .tagline {{ color: var(--text-muted); font-size: 13px; }}
.workspace-badge {{ background: var(--accent); color: #000; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
.tabs {{ display: flex; gap: 0; background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 24px; }}
.tab {{ padding: 12px 20px; cursor: pointer; color: var(--text-muted); border-bottom: 2px solid transparent; font-size: 14px; font-weight: 500; transition: all 0.15s; }}
.tab:hover {{ color: var(--text); }}
.tab.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
.tab .count {{ background: var(--surface2); padding: 1px 8px; border-radius: 10px; font-size: 11px; margin-left: 6px; }}
.content {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; }}
.stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
.stat-value {{ font-size: 28px; font-weight: 700; }}
.stat-label {{ color: var(--text-muted); font-size: 12px; margin-top: 4px; }}
.stat-value.green {{ color: var(--green); }}
.stat-value.orange {{ color: var(--orange); }}
.stat-value.red {{ color: var(--red); }}
.page-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }}
.page-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; cursor: pointer; transition: border-color 0.15s; }}
.page-card:hover {{ border-color: var(--accent); }}
.page-card h3 {{ font-size: 15px; margin-bottom: 6px; }}
.page-card .page-meta {{ color: var(--text-muted); font-size: 12px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; background: var(--surface2); color: var(--text-muted); margin-right: 4px; }}
.badge-entity {{ background: #1f3a5f; color: var(--accent); }}
.badge-source {{ background: #2a1f3f; color: var(--purple); }}
.badge-synthesis {{ background: #1f3f2a; color: var(--green); }}
.badge-concept {{ background: #3f2a1f; color: var(--orange); }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 10px; border-left: 3px solid var(--border); }}
.card-done {{ opacity: 0.7; border-left-color: var(--green); }}
.card-running {{ border-left-color: var(--accent); }}
.card-blocked {{ border-left-color: var(--red); }}
.card-ready {{ border-left-color: var(--green); }}
.card-review {{ border-left-color: var(--orange); }}
.card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 12px; }}
.card-status {{ font-weight: 600; text-transform: uppercase; }}
.card-id {{ color: var(--text-muted); font-family: monospace; }}
.card-priority {{ color: var(--text-muted); }}
.card-title {{ font-size: 14px; font-weight: 600; margin-bottom: 6px; }}
.card-notes {{ color: var(--text-muted); font-size: 13px; line-height: 1.4; }}
.card-meta {{ color: var(--text-muted); font-size: 11px; margin-top: 8px; }}
.card-children {{ margin-top: 8px; padding: 8px; background: var(--surface2); border-radius: 4px; font-size: 12px; }}
.card-children ul {{ margin-left: 16px; margin-top: 4px; }}
.card-children li {{ margin-bottom: 2px; }}
.priority-urgent {{ }}
.priority-high .card-priority {{ color: var(--orange); font-weight: 600; }}
.filter-bar {{ margin-bottom: 16px; display: flex; gap: 8px; flex-wrap: wrap; }}
.filter-btn {{ padding: 6px 14px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text-muted); cursor: pointer; font-size: 13px; transition: all 0.15s; }}
.filter-btn:hover, .filter-btn.active {{ background: var(--accent); color: #000; border-color: var(--accent); }}
.source-item {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 10px; cursor: pointer; transition: border-color 0.15s; }}
.source-item:hover {{ border-color: var(--accent); }}
.source-item h3 {{ font-size: 14px; margin-bottom: 4px; }}
.source-meta {{ color: var(--text-muted); font-size: 12px; }}
.detail-overlay {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 100; justify-content: center; align-items: flex-start; padding: 60px 24px; }}
.detail-overlay.show {{ display: flex; }}
.detail-panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; max-width: 720px; width: 100%; max-height: 80vh; overflow-y: auto; padding: 24px; }}
.detail-panel h2 {{ margin-bottom: 12px; }}
.detail-body {{ line-height: 1.6; font-size: 14px; }}
.detail-body h3 {{ margin-top: 16px; margin-bottom: 8px; color: var(--accent); font-size: 15px; }}
.detail-body ul {{ margin-left: 20px; margin-bottom: 12px; }}
.detail-body li {{ margin-bottom: 4px; }}
.detail-body p {{ margin-bottom: 8px; }}
.detail-meta {{ margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 12px; font-family: monospace; }}
.detail-header {{ margin-bottom: 12px; }}
.close-btn {{ float: right; cursor: pointer; font-size: 20px; color: var(--text-muted); background: none; border: none; }}
.close-btn:hover {{ color: var(--text); }}
.generated {{ text-align: center; color: var(--text-muted); font-size: 11px; padding: 24px; }}
</style>
</head>
<body>
<div class="header">
    <h1>⚒️ Foundry</h1>
    <span class="workspace-badge">{html.escape(workspace_name)}</span>
    <span class="tagline">Check in a conversation. Foundry remembers what matters and tracks what needs doing.</span>
</div>
<div class="tabs">
    <div class="tab active" onclick="showTab('knowledge')">Knowledge <span class="count">{len(knowledge_pages)}</span></div>
    <div class="tab" onclick="showTab('work')">Work <span class="count">{len(cards)}</span></div>
    <div class="tab" onclick="showTab('sources')">Sources <span class="count">{len(sources)}</span></div>
</div>
<div class="content">
    <!-- KNOWLEDGE TAB -->
    <div id="tab-knowledge" class="tab-content active">
        <div class="stats">
            <div class="stat"><div class="stat-value">{len(entities)}</div><div class="stat-label">Entities</div></div>
            <div class="stat"><div class="stat-value">{len(concepts)}</div><div class="stat-label">Concepts / Playbooks</div></div>
            <div class="stat"><div class="stat-value">{len(syntheses)}</div><div class="stat-label">Syntheses</div></div>
            <div class="stat"><div class="stat-value">{len(sources)}</div><div class="stat-label">Sources</div></div>
        </div>
        <div class="page-grid">
            {''.join(f"""
            <div class="page-card" onclick="showPage('page-{p['path'].replace('/', '-').replace('.', '-')}')">
                <div><span class="badge badge-{p['pageType']}">{p['pageType']}</span><span class="badge">{p['folder']}</span></div>
                <h3>{html.escape(p['title'])}</h3>
                <div class="page-meta">{html.escape(p.get('entityType', ''))} · {html.escape(p.get('updatedAt', '')[:10])}</div>
            </div>""" for p in knowledge_pages)}
        </div>
    </div>

    <!-- WORK TAB -->
    <div id="tab-work" class="tab-content">
        <div class="stats">
            <div class="stat"><div class="stat-value{' green' if not active_cards else ''}">{len(active_cards)}</div><div class="stat-label">Active</div></div>
            <div class="stat"><div class="stat-value{' red' if blocked_cards else ''}">{len(blocked_cards)}</div><div class="stat-label">Blocked</div></div>
            <div class="stat"><div class="stat-value green">{len(done_cards)}</div><div class="stat-label">Done</div></div>
            <div class="stat"><div class="stat-value">{len(cards)}</div><div class="stat-label">Total</div></div>
        </div>
        <div class="filter-bar">
            <button class="filter-btn active" onclick="filterCards('all', this)">All</button>
            <button class="filter-btn" onclick="filterCards('running', this)">🔨 Running</button>
            <button class="filter-btn" onclick="filterCards('blocked', this)">🚫 Blocked</button>
            <button class="filter-btn" onclick="filterCards('ready', this)">🟢 Ready</button>
            <button class="filter-btn" onclick="filterCards('todo', this)">📋 Todo</button>
            <button class="filter-btn" onclick="filterCards('done', this)">✅ Done</button>
        </div>
        {cards_html}
    </div>

    <!-- SOURCES TAB -->
    <div id="tab-sources" class="tab-content">
        <div class="stats">
            <div class="stat"><div class="stat-value">{len(sources)}</div><div class="stat-label">Committed Sources</div></div>
        </div>
        {sources_html}
    </div>
</div>

<!-- Page detail overlay -->
<div class="detail-overlay" id="detail-overlay" onclick="closeDetail(event)">
    <div class="detail-panel" onclick="event.stopPropagation()">
        <button class="close-btn" onclick="closeDetail()">&times;</button>
        <div id="detail-content"></div>
    </div>
</div>
{page_details}

<div class="generated">Generated {datetime.now().strftime('%d %b %Y %H:%M')} · Foundry v2 (Rev 7.3)</div>

<script>
function showTab(name) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    event.target.closest('.tab').classList.add('active');
}}
function filterCards(status, btn) {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.card').forEach(c => {{
        c.style.display = (status === 'all' || c.dataset.status === status) ? '' : 'none';
    }});
}}
function showPage(id) {{
    const el = document.getElementById(id);
    if (el) {{
        document.getElementById('detail-content').innerHTML = el.innerHTML;
        document.getElementById('detail-overlay').classList.add('show');
    }}
}}
function closeDetail(e) {{
    if (!e || e.target === document.getElementById('detail-overlay'))
        document.getElementById('detail-overlay').classList.remove('show');
}}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeDetail(); }});
</script>
</body>
</html>'''


def load_manifest(manifest_path):
    """Load the Foundry manifest."""
    with open(manifest_path) as f:
        return json.load(f)


def build_multi_workspace_html(workspaces_data):
    """Generate a multi-workspace dashboard with switcher."""
    workspace_tabs = ""
    workspace_contents = ""
    first = True

    for ws_id, ws in workspaces_data.items():
        active_class = " active" if first else ""
        ws_name = ws["name"]
        pages = ws["pages"]
        cards = ws["cards"]
        card_links = ws["card_links"]

        sources = [p for p in pages if p["folder"] == "sources"]
        entities = [p for p in pages if p["folder"] == "entities"]
        concepts = [p for p in pages if p["folder"] == "concepts"]
        syntheses = [p for p in pages if p["folder"] == "syntheses"]
        knowledge_pages = entities + concepts + syntheses

        active_cards = [c for c in cards if c["status"] not in ("done",)]
        done_cards = [c for c in cards if c["status"] == "done"]
        blocked_cards = [c for c in cards if c["status"] == "blocked"]

        workspace_tabs += f'<button class="ws-btn{active_class}" onclick="switchWorkspace(\'{ws_id}\', this)">{html.escape(ws_name)}</button>'

        # Page details
        page_details = ""
        for p in pages:
            pid = f"{ws_id}-{p['path'].replace('/', '-').replace('.', '-')}"
            body_html = md_to_html_simple(p["body"][:3000])
            page_details += f'''
            <div id="page-{pid}" class="page-detail" style="display:none">
                <div class="detail-header">
                    <span class="badge badge-{p['pageType']}">{p['pageType']}</span>
                    <span class="badge">{p['folder']}</span>
                    {f'<span class="badge badge-status">{p["status"]}</span>' if p["status"] else ''}
                </div>
                <h2>{html.escape(p['title'])}</h2>
                <div class="detail-body">{body_html}</div>
                <div class="detail-meta">Path: {html.escape(p['path'])}</div>
            </div>'''

        # Cards HTML
        cards_html = ""
        for c in cards:
            cid = c["id"][:8]
            emoji = status_emoji(c["status"])
            pclass = priority_class(c["priority"])
            notes_preview = (c["notes"] or "")[:120]
            if len(c["notes"] or "") > 120:
                notes_preview += "…"
            date = ts_to_date(c["created_at"])
            agent = c.get("agent_id") or ""
            agent_badge = f'<span class="badge">{html.escape(agent)}</span>' if agent else ''

            children_html = ""
            if cid in card_links:
                children_items = "".join(
                    f'<li>{ch["title"]} <span class="card-id">({ch["child_id"]})</span></li>'
                    for ch in card_links[cid]
                )
                children_html = f'<div class="card-children"><strong>Sub-cards:</strong><ul>{children_items}</ul></div>'

            # Load card labels
            label_badges = ""
            if "labels" in c and c["labels"]:
                for lbl in c["labels"]:
                    label_badges += f'<span class="badge">{html.escape(lbl)}</span>'

            cards_html += f'''
            <div class="card card-{c['status']} {pclass}" data-status="{c['status']}">
                <div class="card-header">
                    <span class="card-status">{emoji} {c['status']}</span>
                    <span class="card-id">#{cid}</span>
                    <span class="card-priority">{c['priority']}</span>
                    {agent_badge}
                </div>
                <h3 class="card-title">{html.escape(c['title'])}</h3>
                <p class="card-notes">{html.escape(notes_preview)}</p>
                {children_html}
                <div class="card-meta">{date}</div>
            </div>'''

        # Sources HTML
        sources_html = ""
        for s in sources:
            sid = f"{ws_id}-{s['path'].replace('/', '-').replace('.', '-')}"
            sources_html += f'''
            <div class="source-item" onclick="showPage('page-{sid}')">
                <h3>{html.escape(s['title'])}</h3>
                <div class="source-meta">{html.escape(s.get('updatedAt', '')[:10])}</div>
            </div>'''

        workspace_contents += f'''
        <div id="ws-{ws_id}" class="ws-content{active_class}">
            <div class="inner-tabs">
                <div class="tab active" onclick="showInnerTab('{ws_id}', 'knowledge', this)">Knowledge <span class="count">{len(knowledge_pages)}</span></div>
                <div class="tab" onclick="showInnerTab('{ws_id}', 'work', this)">Work <span class="count">{len(cards)}</span></div>
                <div class="tab" onclick="showInnerTab('{ws_id}', 'sources', this)">Sources <span class="count">{len(sources)}</span></div>
            </div>
            <div id="{ws_id}-knowledge" class="inner-tab active">
                <div class="stats">
                    <div class="stat"><div class="stat-value">{len(entities)}</div><div class="stat-label">Entities</div></div>
                    <div class="stat"><div class="stat-value">{len(concepts)}</div><div class="stat-label">Concepts</div></div>
                    <div class="stat"><div class="stat-value">{len(syntheses)}</div><div class="stat-label">Syntheses</div></div>
                    <div class="stat"><div class="stat-value">{len(sources)}</div><div class="stat-label">Sources</div></div>
                </div>
                <div class="page-grid">
                    {''.join(f"""
                    <div class="page-card" onclick="showPage('page-{ws_id}-{p['path'].replace('/', '-').replace('.', '-')}')">
                        <div><span class="badge badge-{p['pageType']}">{p['pageType']}</span><span class="badge">{p['folder']}</span></div>
                        <h3>{html.escape(p['title'])}</h3>
                        <div class="page-meta">{html.escape(p.get('entityType', ''))} · {html.escape(p.get('updatedAt', '')[:10])}</div>
                    </div>""" for p in knowledge_pages) if knowledge_pages else '<p class="empty">No knowledge pages yet. Check in a conversation to get started.</p>'}
                </div>
            </div>
            <div id="{ws_id}-work" class="inner-tab">
                <div class="stats">
                    <div class="stat"><div class="stat-value{' green' if not active_cards else ''}">{len(active_cards)}</div><div class="stat-label">Active</div></div>
                    <div class="stat"><div class="stat-value{' red' if blocked_cards else ''}">{len(blocked_cards)}</div><div class="stat-label">Blocked</div></div>
                    <div class="stat"><div class="stat-value green">{len(done_cards)}</div><div class="stat-label">Done</div></div>
                    <div class="stat"><div class="stat-value">{len(cards)}</div><div class="stat-label">Total</div></div>
                </div>
                <div class="filter-bar">
                    <button class="filter-btn active" onclick="filterCards('{ws_id}', 'all', this)">All</button>
                    <button class="filter-btn" onclick="filterCards('{ws_id}', 'running', this)">Running</button>
                    <button class="filter-btn" onclick="filterCards('{ws_id}', 'blocked', this)">Blocked</button>
                    <button class="filter-btn" onclick="filterCards('{ws_id}', 'ready', this)">Ready</button>
                    <button class="filter-btn" onclick="filterCards('{ws_id}', 'todo', this)">Todo</button>
                    <button class="filter-btn" onclick="filterCards('{ws_id}', 'review', this)">Review</button>
                    <button class="filter-btn" onclick="filterCards('{ws_id}', 'done', this)">Done</button>
                </div>
                <div id="{ws_id}-cards">
                    {cards_html if cards_html else '<p class="empty">No cards on this board yet.</p>'}
                </div>
            </div>
            <div id="{ws_id}-sources" class="inner-tab">
                <div class="stats">
                    <div class="stat"><div class="stat-value">{len(sources)}</div><div class="stat-label">Committed Sources</div></div>
                </div>
                {sources_html if sources_html else '<p class="empty">No sources checked in yet.</p>'}
            </div>
            {page_details}
        </div>'''

        first = False

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Foundry Dashboard</title>
<style>
:root {{
    --bg: #0d1117; --surface: #161b22; --surface2: #21262d;
    --border: #30363d; --text: #e6edf3; --text-muted: #8b949e;
    --accent: #58a6ff; --green: #3fb950; --red: #f85149;
    --orange: #d29922; --purple: #bc8cff;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); }}
.header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; gap: 16px; }}
.header h1 {{ font-size: 20px; font-weight: 600; }}
.header .tagline {{ color: var(--text-muted); font-size: 13px; flex: 1; }}
.ws-switcher {{ display: flex; gap: 6px; padding: 8px 24px; background: var(--surface); border-bottom: 1px solid var(--border); }}
.ws-btn {{ padding: 6px 16px; border-radius: 6px; border: 1px solid var(--border); background: transparent; color: var(--text-muted); cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.15s; }}
.ws-btn:hover {{ color: var(--text); border-color: var(--text-muted); }}
.ws-btn.active {{ background: var(--accent); color: #000; border-color: var(--accent); font-weight: 600; }}
.ws-content {{ display: none; }}
.ws-content.active {{ display: block; }}
.inner-tabs {{ display: flex; gap: 0; background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 24px; }}
.tab {{ padding: 12px 20px; cursor: pointer; color: var(--text-muted); border-bottom: 2px solid transparent; font-size: 14px; font-weight: 500; transition: all 0.15s; }}
.tab:hover {{ color: var(--text); }}
.tab.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
.tab .count {{ background: var(--surface2); padding: 1px 8px; border-radius: 10px; font-size: 11px; margin-left: 6px; }}
.content {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
.inner-tab {{ display: none; }}
.inner-tab.active {{ display: block; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; }}
.stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
.stat-value {{ font-size: 28px; font-weight: 700; }}
.stat-label {{ color: var(--text-muted); font-size: 12px; margin-top: 4px; }}
.stat-value.green {{ color: var(--green); }}
.stat-value.orange {{ color: var(--orange); }}
.stat-value.red {{ color: var(--red); }}
.page-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }}
.page-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; cursor: pointer; transition: border-color 0.15s; }}
.page-card:hover {{ border-color: var(--accent); }}
.page-card h3 {{ font-size: 15px; margin-bottom: 6px; }}
.page-card .page-meta {{ color: var(--text-muted); font-size: 12px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; background: var(--surface2); color: var(--text-muted); margin-right: 4px; }}
.badge-entity {{ background: #1f3a5f; color: var(--accent); }}
.badge-source {{ background: #2a1f3f; color: var(--purple); }}
.badge-synthesis {{ background: #1f3f2a; color: var(--green); }}
.badge-concept {{ background: #3f2a1f; color: var(--orange); }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 10px; border-left: 3px solid var(--border); }}
.card-done {{ opacity: 0.7; border-left-color: var(--green); }}
.card-running {{ border-left-color: var(--accent); }}
.card-blocked {{ border-left-color: var(--red); }}
.card-ready, .card-todo {{ border-left-color: var(--green); }}
.card-review {{ border-left-color: var(--orange); }}
.card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 12px; }}
.card-status {{ font-weight: 600; text-transform: uppercase; }}
.card-id {{ color: var(--text-muted); font-family: monospace; }}
.card-priority {{ color: var(--text-muted); }}
.card-title {{ font-size: 14px; font-weight: 600; margin-bottom: 6px; }}
.card-notes {{ color: var(--text-muted); font-size: 13px; line-height: 1.4; }}
.card-meta {{ color: var(--text-muted); font-size: 11px; margin-top: 8px; }}
.card-children {{ margin-top: 8px; padding: 8px; background: var(--surface2); border-radius: 4px; font-size: 12px; }}
.card-children ul {{ margin-left: 16px; margin-top: 4px; }}
.card-children li {{ margin-bottom: 2px; }}
.priority-high .card-priority {{ color: var(--orange); font-weight: 600; }}
.filter-bar {{ margin-bottom: 16px; display: flex; gap: 8px; flex-wrap: wrap; }}
.filter-btn {{ padding: 6px 14px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text-muted); cursor: pointer; font-size: 13px; transition: all 0.15s; }}
.filter-btn:hover, .filter-btn.active {{ background: var(--accent); color: #000; border-color: var(--accent); }}
.source-item {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 10px; cursor: pointer; transition: border-color 0.15s; }}
.source-item:hover {{ border-color: var(--accent); }}
.source-item h3 {{ font-size: 14px; margin-bottom: 4px; }}
.source-meta {{ color: var(--text-muted); font-size: 12px; }}
.detail-overlay {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 100; justify-content: center; align-items: flex-start; padding: 60px 24px; }}
.detail-overlay.show {{ display: flex; }}
.detail-panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; max-width: 720px; width: 100%; max-height: 80vh; overflow-y: auto; padding: 24px; }}
.detail-panel h2 {{ margin-bottom: 12px; }}
.detail-body {{ line-height: 1.6; font-size: 14px; }}
.detail-body h3 {{ margin-top: 16px; margin-bottom: 8px; color: var(--accent); font-size: 15px; }}
.detail-body ul {{ margin-left: 20px; margin-bottom: 12px; }}
.detail-body li {{ margin-bottom: 4px; }}
.detail-body p {{ margin-bottom: 8px; }}
.detail-meta {{ margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 12px; font-family: monospace; }}
.detail-header {{ margin-bottom: 12px; }}
.close-btn {{ float: right; cursor: pointer; font-size: 20px; color: var(--text-muted); background: none; border: none; }}
.close-btn:hover {{ color: var(--text); }}
.empty {{ color: var(--text-muted); font-style: italic; padding: 24px; text-align: center; }}
.generated {{ text-align: center; color: var(--text-muted); font-size: 11px; padding: 24px; }}
@media (max-width: 640px) {{
    .header {{ flex-wrap: wrap; }}
    .ws-switcher {{ overflow-x: auto; }}
    .page-grid {{ grid-template-columns: 1fr; }}
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
}}
</style>
</head>
<body>
<div class="header">
    <h1>Foundry</h1>
    <span class="tagline">Check in a conversation. Foundry remembers what matters and tracks what needs doing.</span>
</div>
<div class="ws-switcher">
    {workspace_tabs}
</div>
<div class="content">
    {workspace_contents}
</div>

<div class="detail-overlay" id="detail-overlay" onclick="closeDetail(event)">
    <div class="detail-panel" onclick="event.stopPropagation()">
        <button class="close-btn" onclick="closeDetail()">&times;</button>
        <div id="detail-content"></div>
    </div>
</div>

<div class="generated">Generated {datetime.now().strftime('%d %b %Y %H:%M')} · Foundry v2 (Rev 7.3)</div>

<script>
function switchWorkspace(id, btn) {{
    document.querySelectorAll('.ws-content').forEach(w => w.classList.remove('active'));
    document.querySelectorAll('.ws-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('ws-' + id).classList.add('active');
    btn.classList.add('active');
}}
function showInnerTab(ws, tab, el) {{
    const container = document.getElementById('ws-' + ws);
    container.querySelectorAll('.inner-tab').forEach(t => t.classList.remove('active'));
    container.querySelectorAll('.inner-tabs .tab').forEach(t => t.classList.remove('active'));
    document.getElementById(ws + '-' + tab).classList.add('active');
    el.classList.add('active');
}}
function filterCards(ws, status, btn) {{
    const container = document.getElementById(ws + '-cards');
    btn.parentElement.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    container.querySelectorAll('.card').forEach(c => {{
        c.style.display = (status === 'all' || c.dataset.status === status) ? '' : 'none';
    }});
}}
function showPage(id) {{
    const el = document.getElementById(id);
    if (el) {{
        document.getElementById('detail-content').innerHTML = el.innerHTML;
        document.getElementById('detail-overlay').classList.add('show');
    }}
}}
function closeDetail(e) {{
    if (!e || e.target === document.getElementById('detail-overlay'))
        document.getElementById('detail-overlay').classList.remove('show');
}}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeDetail(); }});
</script>
</body>
</html>'''


def main():
    parser = argparse.ArgumentParser(description="Foundry Dashboard Generator")
    parser.add_argument("--manifest", default=os.path.expanduser(
        "~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json"))
    parser.add_argument("--db", default=os.path.expanduser(
        "~/.openclaw/plugins/workboard/workboard.sqlite"))
    parser.add_argument("--out", default="./dist/index.html")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    workspaces_data = {}

    for ws_id, ws_config in manifest["workspaces"].items():
        vault = os.path.expanduser(ws_config["vault"])
        board = ws_config["board"]
        name = ws_config["name"]

        print(f"\n[{name}] Loading wiki vault: {vault}")
        if os.path.exists(vault):
            pages = load_wiki_pages(vault)
        else:
            pages = []
            print(f"  ⚠ Vault not found")
        print(f"  → {len(pages)} pages")

        print(f"[{name}] Loading workboard: board={board}")
        cards = load_workboard_cards(args.db, board)
        print(f"  → {len(cards)} cards")

        links = load_card_links(args.db, board)
        print(f"  → {len(links)} parent cards with children")

        workspaces_data[ws_id] = {
            "name": name,
            "pages": pages,
            "cards": cards,
            "card_links": links,
        }

    html_content = build_multi_workspace_html(workspaces_data)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_content)
    print(f"\nDashboard written to {out_path} ({len(html_content)} bytes)")


if __name__ == "__main__":
    main()
