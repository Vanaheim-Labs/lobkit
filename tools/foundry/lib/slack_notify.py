#!/usr/bin/env python3
"""
Foundry → Slack Event Delivery

Reads Workboard card events, compares against a watermark, and outputs
formatted Slack messages for new events. Designed to be called by an
OpenClaw cron agentTurn — the agent posts the output to Slack.

Usage:
    python3 slack_notify.py                    # Check for new events, output messages
    python3 slack_notify.py --backfill         # Output current board state summary
    python3 slack_notify.py --dry-run          # Show what would be sent without updating watermark
    python3 slack_notify.py --board heimdall   # Specific board (default: all configured)
    python3 slack_notify.py --reset            # Reset watermark (re-deliver all events)

Watermark file: ~/.openclaw/workspace/lobkit/tools/foundry/state/notify-watermark.json
"""

import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# Paths
WORKBOARD_DB = os.path.expanduser("~/.openclaw/plugins/workboard/workboard.sqlite")
MANIFEST_PATH = os.path.expanduser(
    "~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json"
)
STATE_DIR = os.path.expanduser(
    "~/.openclaw/workspace/lobkit/tools/foundry/state"
)
WATERMARK_PATH = os.path.join(STATE_DIR, "notify-watermark.json")

# Event kinds we care about for Slack notifications
NOTIFY_EVENTS = {
    "created": "card.created",
    "claimed": "card.claimed",
    "dispatch": "card.dispatched",
    "status_change": None,  # mapped dynamically based on to_status
    "moved": None,  # mapped dynamically based on to_status
}

# Status transitions worth notifying about
STATUS_NOTIFY_MAP = {
    "running": "card.claimed",
    "done": "card.completed",
    "blocked": "card.blocked",
    "failed": "card.failed",
    "review": "card.review",
    "ready": "card.ready",
    "todo": "card.created",
}

# Emoji for statuses
STATUS_EMOJI = {
    "todo": "📌",
    "ready": "🔜",
    "running": "🔨",
    "review": "👀",
    "done": "✅",
    "blocked": "🚫",
    "failed": "❌",
}


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def load_watermark():
    if not os.path.exists(WATERMARK_PATH):
        return {}
    with open(WATERMARK_PATH) as f:
        return json.load(f)


def save_watermark(watermark):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(WATERMARK_PATH, "w") as f:
        json.dump(watermark, f, indent=2)


def get_db():
    if not os.path.exists(WORKBOARD_DB):
        print(f"ERROR: Workboard database not found at {WORKBOARD_DB}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(f"file:{WORKBOARD_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_configured_boards(manifest):
    """Get boards that have notification channels configured."""
    boards = {}
    for ws_id, ws in manifest.get("workspaces", {}).items():
        notif = ws.get("notifications", {})
        channel = notif.get("channel")
        if channel:
            boards[ws.get("board", ws_id)] = {
                "workspace_id": ws_id,
                "workspace_name": ws.get("name", ws_id),
                "channel": channel,
                "events_on": notif.get("on", {}),
            }
    return boards


def get_new_events(db, board_id, since_ts):
    """Get card events newer than the watermark timestamp."""
    cursor = db.execute("""
        SELECT e.id, e.card_id, e.kind, e.at, e.from_status, e.to_status,
               c.title, c.status as current_status, c.priority, c.agent_id,
               c.failure_count,
               (
                 SELECT body FROM workboard_comments wc
                 WHERE wc.card_id = e.card_id
                   AND lower(wc.body) LIKE 'completed:%'
                 ORDER BY wc.created_at DESC
                 LIMIT 1
               ) as completion_summary
        FROM workboard_card_events e
        JOIN workboard_cards c ON e.card_id = c.id
        WHERE c.board_id = ?
          AND e.at > ?
        ORDER BY e.at ASC
    """, (board_id, since_ts))
    return [dict(row) for row in cursor.fetchall()]


def get_board_summary(db, board_id):
    """Get current board state for backfill."""
    cursor = db.execute("""
        SELECT c.id, c.title, c.status, c.priority, c.agent_id, c.failure_count,
               c.created_at, c.updated_at, c.started_at, c.completed_at,
               (
                 SELECT body FROM workboard_comments wc
                 WHERE wc.card_id = c.id
                   AND lower(wc.body) LIKE 'completed:%'
                 ORDER BY wc.created_at DESC
                 LIMIT 1
               ) as completion_summary
        FROM workboard_cards c
        WHERE c.board_id = ?
        ORDER BY
            CASE c.status
                WHEN 'running' THEN 0
                WHEN 'blocked' THEN 1
                WHEN 'review' THEN 2
                WHEN 'ready' THEN 3
                WHEN 'todo' THEN 4
                WHEN 'done' THEN 5
                WHEN 'failed' THEN 6
            END,
            c.position ASC
    """, (board_id,))
    return [dict(row) for row in cursor.fetchall()]


def should_notify_event(event, events_config):
    """Check if this event type should generate a notification."""
    kind = event["kind"]

    # Status change events — check the target status
    if kind in ("status_change", "moved"):
        to_status = event.get("to_status", "")
        mapped = STATUS_NOTIFY_MAP.get(to_status)
        if mapped and events_config.get(mapped, False):
            return True
        return False

    # Direct event kinds
    if kind == "created":
        return events_config.get("card.created", True)
    if kind == "claimed":
        return events_config.get("card.claimed", True)
    if kind == "dispatch":
        return events_config.get("card.dispatched", False)

    return False


def format_event(event, workspace_name):
    """Format a single event as a Slack mrkdwn message."""
    kind = event["kind"]
    title = event["title"]
    card_id = event["card_id"][:8]
    agent = event.get("agent_id") or "agent"

    if kind in ("status_change", "moved"):
        to_status = event.get("to_status", "unknown")
        from_status = event.get("from_status", "?")
        emoji = STATUS_EMOJI.get(to_status, "❓")

        if to_status == "done":
            summary = event.get("completion_summary")
            if summary:
                # Truncate to 300 chars
                summary_text = summary.strip()
                if len(summary_text) > 300:
                    summary_text = summary_text[:297] + "…"
                return f"{emoji} *Done:* {title}\n> {summary_text}"
            return f"{emoji} *Done:* {title}"
        elif to_status == "blocked":
            return f"{emoji} *Blocked:* {title}"
        elif to_status == "failed":
            failures = event.get("failure_count", 0)
            suffix = f" (attempt {failures})" if failures else ""
            return f"{emoji} *Failed:* {title}{suffix}"
        elif to_status == "running":
            return f"{emoji} *{agent}* picked up: {title}"
        elif to_status == "review":
            return f"{emoji} *Review:* {title}"
        elif to_status == "ready":
            if from_status == "blocked":
                return f"🔓 *Unblocked:* {title} — re-queued"
            return f"{emoji} *Ready:* {title}"
        else:
            return f"{emoji} *{from_status} → {to_status}:* {title}"

    elif kind == "created":
        priority_tag = f" ({event['priority']})" if event.get("priority") not in ("normal", None) else ""
        return f"📌 *New card:* {title}{priority_tag}"

    elif kind == "claimed":
        return f"🔨 *{agent}* claimed: {title}"

    elif kind == "dispatch":
        return f"⚡ *Dispatched:* {title}"

    return f"❓ *{kind}:* {title}"


def format_timestamp(ts_ms):
    """Format a millisecond timestamp as a human-readable time."""
    dt = datetime.fromtimestamp(ts_ms / 1000)
    return dt.strftime("%-I:%M %p").lower()


def format_backfill(cards, workspace_name):
    """Format a full board summary."""
    if not cards:
        return f"📊 *{workspace_name} board:* No cards"

    status_groups = {}
    for card in cards:
        s = card["status"]
        status_groups.setdefault(s, []).append(card)

    lines = [f"📊 *{workspace_name} Workboard — Current State*\n"]

    order = ["running", "blocked", "review", "ready", "todo", "done", "failed"]
    for status in order:
        group = status_groups.get(status, [])
        if not group:
            continue
        emoji = STATUS_EMOJI.get(status, "❓")
        lines.append(f"*{emoji} {status.title()} ({len(group)})*")
        for card in group:
            title = card["title"]
            if len(title) > 80:
                title = title[:77] + "…"
            agent_tag = f" — {card['agent_id']}" if card.get("agent_id") else ""
            lines.append(f"• {title}{agent_tag}")
            # Show completion summary for done cards if available
            if status == "done" and card.get("completion_summary"):
                summary = card["completion_summary"].strip()
                if len(summary) > 200:
                    summary = summary[:197] + "…"
                lines.append(f"  > {summary}")
        lines.append("")

    total = len(cards)
    done = len(status_groups.get("done", []))
    active = total - done
    lines.append(f"_{active} active, {done} done, {total} total_")

    return "\n".join(lines)


def run_check(board_filter=None, dry_run=False):
    """Main check: find new events, output formatted messages."""
    manifest = load_manifest()
    watermark = load_watermark()
    boards = get_configured_boards(manifest)
    db = get_db()

    results = {}  # channel → [messages]

    for board_id, config in boards.items():
        if board_filter and board_id != board_filter:
            continue

        channel = config["channel"]
        ws_name = config["workspace_name"]
        since_ts = watermark.get(board_id, 0)

        events = get_new_events(db, board_id, since_ts)

        if not events:
            continue

        messages = []
        max_ts = since_ts

        for event in events:
            if event["at"] > max_ts:
                max_ts = event["at"]

            if should_notify_event(event, config["events_on"]):
                msg = format_event(event, ws_name)
                messages.append(msg)

        if messages:
            results.setdefault(channel, {
                "workspace": ws_name,
                "messages": [],
            })
            results[channel]["messages"].extend(messages)

        if not dry_run:
            watermark[board_id] = max_ts

    db.close()

    if not dry_run:
        save_watermark(watermark)

    return results


def run_backfill(board_filter=None):
    """Output current board state."""
    manifest = load_manifest()
    boards = get_configured_boards(manifest)
    db = get_db()

    results = {}

    for board_id, config in boards.items():
        if board_filter and board_id != board_filter:
            continue

        channel = config["channel"]
        ws_name = config["workspace_name"]
        cards = get_board_summary(db, board_id)
        msg = format_backfill(cards, ws_name)

        results[channel] = {
            "workspace": ws_name,
            "messages": [msg],
        }

    db.close()
    return results


# Slack bot token config path
OPENCLAW_CONFIG = os.path.expanduser("~/.openclaw/openclaw.json")


def get_slack_token(account_id="default"):
    """Read Slack bot token from OpenClaw config."""
    with open(OPENCLAW_CONFIG) as f:
        config = json.load(f)
    accounts = config.get("channels", {}).get("slack", {}).get("accounts", {})
    account = accounts.get(account_id, {})
    token = account.get("botToken")
    if not token:
        print(f"ERROR: No Slack bot token for account '{account_id}'", file=sys.stderr)
        sys.exit(1)
    return token


def post_to_slack(channel_id, text, token):
    """Post a message to Slack using the Web API."""
    url = "https://slack.com/api/chat.postMessage"
    payload = json.dumps({
        "channel": channel_id,
        "text": text,
        "unfurl_links": False,
        "unfurl_media": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                print(f"Slack API error: {result.get('error', 'unknown')}", file=sys.stderr)
                return False
            return True
    except urllib.error.URLError as e:
        print(f"Slack post failed: {e}", file=sys.stderr)
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Foundry → Slack Event Delivery")
    parser.add_argument("--backfill", action="store_true", help="Output full board state")
    parser.add_argument("--dry-run", action="store_true", help="Don't update watermark")
    parser.add_argument("--board", type=str, help="Filter to specific board")
    parser.add_argument("--reset", action="store_true", help="Reset watermark")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--post", action="store_true", help="Post directly to Slack")
    parser.add_argument("--account", type=str, default="default", help="Slack account ID")
    args = parser.parse_args()

    if args.reset:
        save_watermark({})
        print("Watermark reset.", file=sys.stderr)
        if not args.backfill:
            return

    if args.backfill:
        results = run_backfill(args.board)
    else:
        results = run_check(args.board, args.dry_run)

    if not results:
        if not args.json:
            print("NO_EVENTS", file=sys.stderr)
        else:
            print(json.dumps({"events": False}))
        return

    if args.post:
        # Post directly to Slack
        token = get_slack_token(args.account)
        posted = 0
        for channel_id, data in results.items():
            combined = "\n".join(data["messages"])
            if post_to_slack(channel_id, combined, token):
                posted += len(data["messages"])
                print(f"Posted {len(data['messages'])} events to {data['workspace']} ({channel_id})")
            else:
                print(f"FAILED to post to {channel_id}", file=sys.stderr)
        if posted:
            print(f"Total: {posted} events delivered")
    elif args.json:
        print(json.dumps(results, indent=2))
    else:
        # Output for agent consumption: channel\tmessage per line
        for channel, data in results.items():
            for msg in data["messages"]:
                print(f"NOTIFY\t{channel}\t{data['workspace']}\t{msg}")


if __name__ == "__main__":
    main()
