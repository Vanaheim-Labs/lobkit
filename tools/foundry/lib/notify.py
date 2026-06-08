#!/usr/bin/env python3
"""
Foundry Event Delivery — Notification Formatter

Formats Foundry events into Slack mrkdwn messages.
Used by the check-in procedure and can be called standalone.

Usage:
    # Format a check-in notification
    python3 notify.py checkin --title "Architecture discussion" --pages 3 --cards 2 --workspace Heimdall

    # Format a card event
    python3 notify.py card --event completed --title "Build resolver" --proof "resolver.py tested"
    python3 notify.py card --event blocked --title "Migration scope" --question "Which data to migrate?"
    python3 notify.py card --event claimed --title "Build resolver" --agent Mimir

    # Format a decision
    python3 notify.py decision --text "Agent-routed manifest" --page "entity.foundry"
"""

import argparse
import sys


def format_checkin(title, pages=0, cards=0, decisions=0, workspace=""):
    parts = []
    if pages:
        parts.append(f"{pages} page{'s' if pages != 1 else ''} updated")
    if cards:
        parts.append(f"{cards} card{'s' if cards != 1 else ''} created")
    if decisions:
        parts.append(f"{decisions} decision{'s' if decisions != 1 else ''} recorded")
    detail = " — " + ", ".join(parts) if parts else ""
    ws = f" to {workspace}" if workspace else ""
    return f"📥 *Checked in{ws}:* {title}{detail}"


def format_card_event(event, title, **kwargs):
    formats = {
        "created": lambda: f"📌 *New card:* {title} ({kwargs.get('priority', 'normal')})",
        "claimed": lambda: f"🔨 *{kwargs.get('agent', 'Agent')}* picked up: *{title}*",
        "completed": lambda: f"✅ *Done:* {title}" + (f" — {kwargs['proof']}" if kwargs.get('proof') else ""),
        "blocked": lambda: f"🚫 *Blocked:* {title}" + (f" — {kwargs['question']}" if kwargs.get('question') else ""),
        "failed": lambda: f"❌ *Failed:* {title}" + (f" — {kwargs['reason']}" if kwargs.get('reason') else ""),
        "unblocked": lambda: f"🔓 *Unblocked:* {title} — re-queued",
    }
    formatter = formats.get(event)
    if not formatter:
        return f"❓ *{event}:* {title}"
    return formatter()


def format_decision(text, page=""):
    on_page = f" — on {page}" if page else ""
    return f"📋 *Decision:* {text}{on_page}"


def format_digest(workspace, checkins=0, cards_worked=0, blocked=0, decisions=0):
    parts = []
    if checkins:
        parts.append(f"{checkins} check-in{'s' if checkins != 1 else ''}")
    if cards_worked:
        parts.append(f"{cards_worked} card{'s' if cards_worked != 1 else ''} worked")
    if blocked:
        parts.append(f"{blocked} blocked")
    if decisions:
        parts.append(f"{decisions} decision{'s' if decisions != 1 else ''}")
    return f"📊 *{workspace} today:* {', '.join(parts)}" if parts else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Foundry Event Notification Formatter")
    sub = parser.add_subparsers(dest="cmd")

    ci = sub.add_parser("checkin")
    ci.add_argument("--title", required=True)
    ci.add_argument("--pages", type=int, default=0)
    ci.add_argument("--cards", type=int, default=0)
    ci.add_argument("--decisions", type=int, default=0)
    ci.add_argument("--workspace", default="")

    card = sub.add_parser("card")
    card.add_argument("--event", required=True)
    card.add_argument("--title", required=True)
    card.add_argument("--agent", default="")
    card.add_argument("--proof", default="")
    card.add_argument("--question", default="")
    card.add_argument("--reason", default="")
    card.add_argument("--priority", default="normal")

    dec = sub.add_parser("decision")
    dec.add_argument("--text", required=True)
    dec.add_argument("--page", default="")

    dig = sub.add_parser("digest")
    dig.add_argument("--workspace", required=True)
    dig.add_argument("--checkins", type=int, default=0)
    dig.add_argument("--cards-worked", type=int, default=0)
    dig.add_argument("--blocked", type=int, default=0)
    dig.add_argument("--decisions", type=int, default=0)

    args = parser.parse_args()

    if args.cmd == "checkin":
        print(format_checkin(args.title, args.pages, args.cards, args.decisions, args.workspace))
    elif args.cmd == "card":
        print(format_card_event(args.event, args.title, agent=args.agent,
                                proof=args.proof, question=args.question,
                                reason=args.reason, priority=args.priority))
    elif args.cmd == "decision":
        print(format_decision(args.text, args.page))
    elif args.cmd == "digest":
        msg = format_digest(args.workspace, args.checkins, args.cards_worked, args.blocked, args.decisions)
        if msg:
            print(msg)
    else:
        parser.print_help()
        sys.exit(1)
