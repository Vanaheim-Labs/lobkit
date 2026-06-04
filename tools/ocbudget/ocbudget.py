#!/usr/bin/env python3
"""
ocbudget — OpenClaw cost and token tracker
Summarises token usage and cost across all agents and sessions.

Usage:
  python3 ocbudget.py                    # summary for last 30 days
  python3 ocbudget.py --days 7           # last 7 days
  python3 ocbudget.py --today            # today only
  python3 ocbudget.py --all              # all time
  python3 ocbudget.py --by-agent         # break down by agent (default)
  python3 ocbudget.py --by-model         # break down by model
  python3 ocbudget.py --by-day           # break down by day
  python3 ocbudget.py --by-session       # most expensive sessions
  python3 ocbudget.py sif themis         # specific agents only
  python3 ocbudget.py --csv              # CSV output
  python3 ocbudget.py --json             # JSON output
"""

import os, sys, json, glob, argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict

AGENTS_DIR = os.path.expanduser("~/.openclaw/agents")

# ── ANSI ─────────────────────────────────────────────────────────────────────
R     = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
RED   = "\033[31m"
GRN   = "\033[32m"
YLW   = "\033[33m"
BLU   = "\033[34m"
MAG   = "\033[35m"
CYN   = "\033[36m"
WHT   = "\033[37m"
GRY   = "\033[90m"

def no_colour():
    global R, BOLD, DIM, RED, GRN, YLW, BLU, MAG, CYN, WHT, GRY
    R = BOLD = DIM = RED = GRN = YLW = BLU = MAG = CYN = WHT = GRY = ""

# ── Cost formatting ───────────────────────────────────────────────────────────
def fmt_cost(c):
    if c == 0:
        return f"{GRY}$0.00{R}"
    if c < 0.001:
        return f"{GRY}${c:.5f}{R}"
    if c < 0.01:
        return f"{YLW}${c:.4f}{R}"
    if c < 1.0:
        return f"{YLW}${c:.3f}{R}"
    if c < 10.0:
        return f"{RED}${c:.2f}{R}"
    return f"{RED}{BOLD}${c:.2f}{R}"

def fmt_cost_plain(c):
    if c == 0: return "$0.00"
    if c < 0.001: return f"${c:.5f}"
    if c < 0.01: return f"${c:.4f}"
    if c < 1.0: return f"${c:.3f}"
    return f"${c:.2f}"

def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

def cost_bar(cost, max_cost, width=20):
    if max_cost == 0:
        return " " * width
    ratio = min(cost / max_cost, 1.0)
    filled = int(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    if ratio > 0.7:
        return f"{RED}{bar}{R}"
    if ratio > 0.3:
        return f"{YLW}{bar}{R}"
    return f"{GRN}{bar}{R}"

# ── Data loading ──────────────────────────────────────────────────────────────
def load_data(agent_filter=None, since_ts=None):
    """
    Returns list of turn dicts:
    {
      agent, session_id, timestamp, model, provider,
      input_tokens, output_tokens, cache_read, cache_write, total_tokens,
      cost_input, cost_output, cost_cache_read, cost_cache_write, cost_total
    }
    """
    turns = []

    if not os.path.isdir(AGENTS_DIR):
        print(f"{RED}Error:{R} agents directory not found: {AGENTS_DIR}", file=sys.stderr)
        sys.exit(1)

    agents = sorted(os.listdir(AGENTS_DIR))
    if agent_filter:
        agents = [a for a in agents if a in agent_filter]

    for agent in agents:
        sessions_dir = os.path.join(AGENTS_DIR, agent, "sessions")
        if not os.path.isdir(sessions_dir):
            continue

        for fpath in glob.glob(os.path.join(sessions_dir, "*.jsonl")):
            if "trajectory" in fpath:
                continue

            session_id = os.path.basename(fpath).replace(".jsonl", "")

            try:
                with open(fpath, "r", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if obj.get("type") != "message":
                            continue
                        msg = obj.get("message", {})
                        if msg.get("role") != "assistant":
                            continue
                        usage = msg.get("usage")
                        if not usage:
                            continue

                        ts_str = obj.get("timestamp", "")
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        except Exception:
                            continue

                        if since_ts and ts < since_ts:
                            continue

                        cost = usage.get("cost", {})

                        turns.append({
                            "agent":           agent,
                            "session_id":      session_id,
                            "timestamp":       ts,
                            "model":           msg.get("model", "unknown"),
                            "provider":        msg.get("provider", "unknown"),
                            "input_tokens":    usage.get("input", 0),
                            "output_tokens":   usage.get("output", 0),
                            "cache_read":      usage.get("cacheRead", 0),
                            "cache_write":     usage.get("cacheWrite", 0),
                            "total_tokens":    usage.get("totalTokens", 0),
                            "cost_input":      cost.get("input", 0),
                            "cost_output":     cost.get("output", 0),
                            "cost_cache_read": cost.get("cacheRead", 0),
                            "cost_cache_write":cost.get("cacheWrite", 0),
                            "cost_total":      cost.get("total", 0),
                        })
            except Exception:
                continue

    return turns

# ── Aggregation helpers ───────────────────────────────────────────────────────
def aggregate(turns, key_fn):
    buckets = defaultdict(lambda: {
        "turns": 0,
        "input_tokens": 0, "output_tokens": 0,
        "cache_read": 0, "cache_write": 0, "total_tokens": 0,
        "cost_input": 0, "cost_output": 0,
        "cost_cache_read": 0, "cost_cache_write": 0, "cost_total": 0,
    })
    for t in turns:
        k = key_fn(t)
        b = buckets[k]
        b["turns"]          += 1
        b["input_tokens"]   += t["input_tokens"]
        b["output_tokens"]  += t["output_tokens"]
        b["cache_read"]     += t["cache_read"]
        b["cache_write"]    += t["cache_write"]
        b["total_tokens"]   += t["total_tokens"]
        b["cost_input"]     += t["cost_input"]
        b["cost_output"]    += t["cost_output"]
        b["cost_cache_read"]+= t["cost_cache_read"]
        b["cost_cache_write"]+= t["cost_cache_write"]
        b["cost_total"]     += t["cost_total"]
    return buckets

def totals(turns):
    return aggregate(turns, lambda _: "total")["total"]

# ── Display modes ─────────────────────────────────────────────────────────────
def print_header(title, period_label):
    w = 72
    print()
    print(f"{BOLD}{'─' * w}{R}")
    print(f"{BOLD}  💸 ocbudget  {GRY}—{R}{BOLD}  {title}{R}  {GRY}{period_label}{R}")
    print(f"{BOLD}{'─' * w}{R}")

def print_totals_bar(t):
    print()
    print(f"  {BOLD}Total cost:    {R}{fmt_cost(t['cost_total'])}  "
          f"{GRY}({fmt_tokens(t['total_tokens'])} tokens, {t['turns']:,} turns){R}")
    print(f"  {DIM}  ├ input:       {fmt_cost_plain(t['cost_input'])}  ({fmt_tokens(t['input_tokens'])}){R}")
    print(f"  {DIM}  ├ output:      {fmt_cost_plain(t['cost_output'])}  ({fmt_tokens(t['output_tokens'])}){R}")
    print(f"  {DIM}  ├ cache read:  {fmt_cost_plain(t['cost_cache_read'])}  ({fmt_tokens(t['cache_read'])}){R}")
    print(f"  {DIM}  └ cache write: {fmt_cost_plain(t['cost_cache_write'])}  ({fmt_tokens(t['cache_write'])}){R}")
    print()

def print_table(rows, col_label, max_rows=40):
    """rows: list of (label, bucket_dict), sorted by cost desc"""
    if not rows:
        print(f"  {GRY}No data.{R}")
        return

    max_cost = max(r[1]["cost_total"] for r in rows) if rows else 1
    label_w = max(len(str(r[0])) for r in rows)
    label_w = max(label_w, len(col_label))

    header = (f"  {BOLD}{col_label:<{label_w}}  {'COST':>10}  {'TOKENS':>8}  "
              f"{'TURNS':>6}  {'BREAKDOWN':<22}{R}")
    print(header)
    print(f"  {'─' * label_w}  {'─'*10}  {'─'*8}  {'─'*6}  {'─'*22}")

    for i, (label, b) in enumerate(rows):
        if i >= max_rows:
            print(f"  {GRY}  … {len(rows) - max_rows} more rows (use --top 0 to show all){R}")
            break
        bar = cost_bar(b["cost_total"], max_cost)
        print(f"  {CYN}{str(label):<{label_w}}{R}  "
              f"{fmt_cost(b['cost_total']):>10}  "
              f"{GRY}{fmt_tokens(b['total_tokens']):>8}{R}  "
              f"{GRY}{b['turns']:>6,}{R}  "
              f"{bar}")
    print()

def show_by_agent(turns):
    buckets = aggregate(turns, lambda t: t["agent"])
    rows = sorted(buckets.items(), key=lambda x: -x[1]["cost_total"])
    print_table(rows, "AGENT")

def show_by_model(turns):
    buckets = aggregate(turns, lambda t: t["model"])
    rows = sorted(buckets.items(), key=lambda x: -x[1]["cost_total"])
    print_table(rows, "MODEL")

def show_by_day(turns):
    buckets = aggregate(turns, lambda t: t["timestamp"].strftime("%Y-%m-%d"))
    rows = sorted(buckets.items(), key=lambda x: x[0])  # chronological
    print_table(rows, "DATE")

def show_by_session(turns, top_n=20):
    buckets = aggregate(turns, lambda t: (t["agent"], t["session_id"]))
    rows = sorted(buckets.items(), key=lambda x: -x[1]["cost_total"])

    max_cost = max(r[1]["cost_total"] for r in rows) if rows else 1
    print(f"  {BOLD}{'AGENT':<14}  {'SESSION':>36}  {'COST':>10}  {'TOKENS':>8}  {'TURNS':>6}{R}")
    print(f"  {'─'*14}  {'─'*36}  {'─'*10}  {'─'*8}  {'─'*6}")

    for i, ((agent, sid), b) in enumerate(rows):
        if i >= top_n:
            print(f"  {GRY}  … {len(rows) - top_n} more sessions{R}")
            break
        # find first/last timestamp for this session
        sess_turns = [t for t in turns if t["agent"] == agent and t["session_id"] == sid]
        first_ts = min(t["timestamp"] for t in sess_turns)
        date_str = first_ts.strftime("%Y-%m-%d %H:%M")
        print(f"  {CYN}{agent:<14}{R}  {GRY}{sid[:36]}{R}  "
              f"{fmt_cost(b['cost_total']):>10}  "
              f"{GRY}{fmt_tokens(b['total_tokens']):>8}{R}  "
              f"{GRY}{b['turns']:>6,}{R}  {DIM}{date_str}{R}")
    print()

# ── CSV / JSON output ─────────────────────────────────────────────────────────
def output_csv(turns, mode):
    import csv, io
    out = io.StringIO()
    w = csv.writer(out)

    if mode == "agent":
        buckets = aggregate(turns, lambda t: t["agent"])
        rows = sorted(buckets.items(), key=lambda x: -x[1]["cost_total"])
        w.writerow(["agent","cost_total","total_tokens","input_tokens","output_tokens",
                    "cache_read","cache_write","turns"])
        for label, b in rows:
            w.writerow([label, round(b["cost_total"],6), b["total_tokens"],
                        b["input_tokens"], b["output_tokens"],
                        b["cache_read"], b["cache_write"], b["turns"]])

    elif mode == "model":
        buckets = aggregate(turns, lambda t: t["model"])
        rows = sorted(buckets.items(), key=lambda x: -x[1]["cost_total"])
        w.writerow(["model","cost_total","total_tokens","turns"])
        for label, b in rows:
            w.writerow([label, round(b["cost_total"],6), b["total_tokens"], b["turns"]])

    elif mode == "day":
        buckets = aggregate(turns, lambda t: t["timestamp"].strftime("%Y-%m-%d"))
        rows = sorted(buckets.items())
        w.writerow(["date","cost_total","total_tokens","turns"])
        for label, b in rows:
            w.writerow([label, round(b["cost_total"],6), b["total_tokens"], b["turns"]])

    else:  # raw turns
        w.writerow(["agent","session_id","timestamp","model","provider",
                    "input_tokens","output_tokens","cache_read","cache_write",
                    "total_tokens","cost_total"])
        for t in sorted(turns, key=lambda x: x["timestamp"]):
            w.writerow([t["agent"], t["session_id"],
                        t["timestamp"].isoformat(), t["model"], t["provider"],
                        t["input_tokens"], t["output_tokens"],
                        t["cache_read"], t["cache_write"],
                        t["total_tokens"], round(t["cost_total"],6)])

    print(out.getvalue(), end="")

def output_json(turns, mode):
    if mode == "agent":
        buckets = aggregate(turns, lambda t: t["agent"])
        data = {k: {**v} for k, v in buckets.items()}
    elif mode == "model":
        buckets = aggregate(turns, lambda t: t["model"])
        data = {k: {**v} for k, v in buckets.items()}
    elif mode == "day":
        buckets = aggregate(turns, lambda t: t["timestamp"].strftime("%Y-%m-%d"))
        data = {k: {**v} for k, v in sorted(buckets.items())}
    else:
        data = [
            {**t, "timestamp": t["timestamp"].isoformat()}
            for t in sorted(turns, key=lambda x: x["timestamp"])
        ]
    print(json.dumps(data, indent=2))

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="ocbudget — OpenClaw cost and token tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    p.add_argument("agents", nargs="*", help="Filter to specific agents")
    p.add_argument("--days",       type=int, default=30,  help="Look back N days (default: 30)")
    p.add_argument("--today",      action="store_true",   help="Today only")
    p.add_argument("--all",        action="store_true",   help="All time")
    p.add_argument("--by-agent",   action="store_true",   help="Break down by agent (default)")
    p.add_argument("--by-model",   action="store_true",   help="Break down by model")
    p.add_argument("--by-day",     action="store_true",   help="Break down by day")
    p.add_argument("--by-session", action="store_true",   help="Most expensive sessions")
    p.add_argument("--top",        type=int, default=20,  help="Max rows per table (0 = all)")
    p.add_argument("--csv",        action="store_true",   help="CSV output")
    p.add_argument("--json",       action="store_true",   help="JSON output")
    p.add_argument("--no-colour",  action="store_true",   help="Disable colour output")
    args = p.parse_args()

    if args.no_colour or not sys.stdout.isatty():
        no_colour()

    # Determine time window
    now = datetime.now(timezone.utc)
    if args.all:
        since_ts = None
        period = "all time"
    elif args.today:
        since_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period = "today"
    else:
        since_ts = now - timedelta(days=args.days)
        period = f"last {args.days} days"

    agent_filter = set(args.agents) if args.agents else None

    # Load data
    turns = load_data(agent_filter=agent_filter, since_ts=since_ts)

    if not turns:
        print(f"\n{YLW}No data found{R} for the specified period/agents.\n")
        sys.exit(0)

    # Determine display mode
    modes = []
    if args.by_model:   modes.append("model")
    if args.by_day:     modes.append("day")
    if args.by_session: modes.append("session")
    if args.by_agent or not modes:
        modes = ["agent"] + [m for m in modes if m != "agent"]

    top_n = args.top if args.top > 0 else 9999

    # CSV / JSON fast paths
    if args.csv:
        output_csv(turns, modes[0])
        return
    if args.json:
        output_json(turns, modes[0])
        return

    # Human-readable output
    agent_label = f" ({', '.join(sorted(agent_filter))})" if agent_filter else ""
    print_header(f"Usage report{agent_label}", period)

    t = totals(turns)
    print_totals_bar(t)

    for mode in modes:
        if mode == "agent":
            print(f"  {BOLD}By agent:{R}")
            show_by_agent(turns)
        elif mode == "model":
            print(f"  {BOLD}By model:{R}")
            show_by_model(turns)
        elif mode == "day":
            print(f"  {BOLD}By day:{R}")
            show_by_day(turns)
        elif mode == "session":
            print(f"  {BOLD}Top sessions by cost:{R}")
            show_by_session(turns, top_n=top_n)

    print(f"  {GRY}Run with --by-model, --by-day, --by-session for more breakdowns.{R}")
    print(f"  {GRY}Use --csv or --json for machine-readable output.{R}\n")

if __name__ == "__main__":
    main()
