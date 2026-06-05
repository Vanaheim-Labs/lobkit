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

import os, sys, json, glob, argparse, re
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

# ── Session label extraction ─────────────────────────────────────────────────
def extract_session_label(first_msg):
    """Derive a human-readable label from the first user message in a session."""
    if not first_msg:
        return None

    # Cron job: [cron:<id> <name>]
    m = re.search(r'\[cron:[a-f0-9-]+ ([^\]]+)\]', first_msg)
    if m:
        return f'cron: {m.group(1)[:44]}'

    # Heartbeat
    if '[OpenClaw heartbeat' in first_msg or 'heartbeat poll' in first_msg.lower():
        return 'heartbeat'

    # Subagent task
    if '[Subagent Task]' in first_msg:
        m = re.search(r'\[Subagent Task\]\s*(.{0,60})', first_msg)
        return f'subagent: {m.group(1).strip()}' if m else 'subagent'

    # Slack message in #channel from Sender: Slack message in #X from Y
    m = re.search(r'Slack message in (#\S+) from (\w+)', first_msg)
    if m:
        return f'{m.group(1)} / {m.group(2)}'

    # Conversation info JSON envelope (newer sessions)
    m = re.search(r'"conversation_label":\s*"([^"]+)"', first_msg)
    if m:
        sender = re.search(r'"sender":\s*"([^"]+)"', first_msg)
        label = m.group(1)
        if sender:
            label += f' / {sender.group(1)}'
        return label

    m = re.search(r'"chat_id":\s*"channel:(\w+)"', first_msg)
    if m:
        return m.group(1)

    # Telegram / WhatsApp system prefix
    m = re.search(r'\[(\d{4}-\d{2}-\d{2}[^\]]+)\]\s*(?:Telegram|WhatsApp)[^:]+:\s*(.{0,60})', first_msg)
    if m:
        return f'telegram: {m.group(2).strip()}'

    return None


def session_label_cache(agents_dir):
    """Build a dict mapping (agent, session_id) -> human label."""
    cache = {}
    for fpath in glob.glob(os.path.join(agents_dir, '*/sessions/*.jsonl')):
        if 'trajectory' in fpath:
            continue
        parts = fpath.split('/agents/')
        if len(parts) < 2:
            continue
        agent = parts[1].split('/')[0]
        session_id = os.path.basename(fpath).replace('.jsonl', '')
        try:
            with open(fpath, 'r', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get('type') != 'message':
                        continue
                    if obj.get('message', {}).get('role') != 'user':
                        continue
                    content = obj['message'].get('content', [])
                    text = ''
                    for c in content:
                        if isinstance(c, dict) and c.get('type') == 'text':
                            text = c['text'][:500]
                            break
                        elif isinstance(c, str):
                            text = c[:500]
                            break
                    label = extract_session_label(text)
                    if label:
                        cache[(agent, session_id)] = label
                    break  # only need first user message
        except Exception:
            pass
    return cache


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

# ── Time bucketing & sparklines ───────────────────────────────────────────────
SPARK_CHARS = "▁▂▃▄▅▆▇█"  # 8 levels; empty bucket renders as " "

def auto_bucket(since_ts, until_ts, today_flag):
    """Choose a sensible bucket granularity for the window."""
    if today_flag:
        return "hour"
    if since_ts is None:
        return "week"  # --all
    span_days = max(1, (until_ts - since_ts).total_seconds() / 86400)
    if span_days <= 2:
        return "hour"
    if span_days <= 90:
        return "day"
    return "week"

def bucket_key(ts, bucket):
    if bucket == "hour":
        return ts.strftime("%Y-%m-%d %H:00")
    if bucket == "day":
        return ts.strftime("%Y-%m-%d")
    if bucket == "week":
        iso = ts.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    raise ValueError(f"unknown bucket: {bucket}")

def bucket_list(since_ts, until_ts, bucket):
    """Ordered list of bucket keys covering [since_ts, until_ts], inclusive of empties."""
    keys = []
    if bucket == "hour":
        cur = since_ts.replace(minute=0, second=0, microsecond=0)
        end = until_ts.replace(minute=0, second=0, microsecond=0)
        while cur <= end:
            keys.append(cur.strftime("%Y-%m-%d %H:00"))
            cur += timedelta(hours=1)
    elif bucket == "day":
        cur = since_ts.replace(hour=0, minute=0, second=0, microsecond=0)
        while cur.date() <= until_ts.date():
            keys.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
    elif bucket == "week":
        cur = since_ts - timedelta(days=since_ts.weekday())
        cur = cur.replace(hour=0, minute=0, second=0, microsecond=0)
        end = until_ts - timedelta(days=until_ts.weekday())
        end = end.replace(hour=0, minute=0, second=0, microsecond=0)
        while cur <= end:
            iso = cur.isocalendar()
            keys.append(f"{iso[0]}-W{iso[1]:02d}")
            cur += timedelta(days=7)
    return keys

def sparkline(values, max_val):
    """Render values as sparkline; per-row scaling means caller passes that row's max."""
    if max_val <= 0:
        return " " * len(values)
    out = []
    n = len(SPARK_CHARS)
    for v in values:
        if v <= 0:
            out.append(" ")
        else:
            # Map (0, max_val] -> [0, n-1]
            idx = int((v / max_val) * (n - 1) + 0.5)
            idx = max(0, min(n - 1, idx))
            out.append(SPARK_CHARS[idx])
    return "".join(out)

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

def show_by_session(turns, top_n=20, label_cache=None):
    buckets = aggregate(turns, lambda t: (t["agent"], t["session_id"]))
    rows = sorted(buckets.items(), key=lambda x: -x[1]["cost_total"])

    print(f"  {BOLD}{'AGENT':<14}  {'COST':>10}  {'TOKENS':>8}  {'TURNS':>6}  {'LABEL / SESSION'}{R}")
    print(f"  {'─'*14}  {'─'*10}  {'─'*8}  {'─'*6}  {'─'*44}")

    for i, ((agent, sid), b) in enumerate(rows):
        if i >= top_n:
            print(f"  {GRY}  … {len(rows) - top_n} more sessions{R}")
            break
        sess_turns = [t for t in turns if t["agent"] == agent and t["session_id"] == sid]
        first_ts = min(t["timestamp"] for t in sess_turns)
        date_str = first_ts.strftime("%m-%d %H:%M")

        label = label_cache.get((agent, sid)) if label_cache else None
        if label:
            label_str = f"{GRN}{label[:44]}{R}  {DIM}{date_str}{R}"
        else:
            label_str = f"{GRY}{sid[:36]}  {date_str}{R}"

        print(f"  {CYN}{agent:<14}{R}  "
              f"{fmt_cost(b['cost_total']):>10}  "
              f"{GRY}{fmt_tokens(b['total_tokens']):>8}{R}  "
              f"{GRY}{b['turns']:>6,}{R}  "
              f"{label_str}")
    print()

# ── Trend (time series) ───────────────────────────────────────────────────────
def _trend_entity_fns(dimension, label_cache):
    """Return (key_fn, fmt_fn, col_label) for the trend dimension."""
    if dimension == "agent":
        return (lambda t: t["agent"], lambda k: str(k), "AGENT")
    if dimension == "model":
        return (lambda t: t["model"], lambda k: str(k), "MODEL")
    if dimension == "session":
        def fmt(k):
            agent, sid = k
            label = label_cache.get(k) if label_cache else None
            if label:
                return f"{agent}/{label[:30]}"
            return f"{agent}/{sid[:8]}"
        return (lambda t: (t["agent"], t["session_id"]), fmt, "SESSION")
    raise ValueError(f"unknown trend dimension: {dimension}")

def build_trend(turns, dimension, since_ts, until_ts, bucket, label_cache=None):
    """
    Build a time-bucketed matrix.
    Returns: (buckets, rows) where
      buckets = ordered list of bucket-key strings
      rows = list of {entity, label, values, cost_total, total_tokens, turns}
             sorted by cost_total desc
    """
    key_fn, fmt_fn, col_label = _trend_entity_fns(dimension, label_cache)

    # Window: derive from turns when --all
    if since_ts is None:
        since_ts = min(t["timestamp"] for t in turns)
    if until_ts is None:
        until_ts = max(t["timestamp"] for t in turns)

    buckets = bucket_list(since_ts, until_ts, bucket)
    bucket_idx = {b: i for i, b in enumerate(buckets)}

    matrix = defaultdict(lambda: [0.0] * len(buckets))
    summary = defaultdict(lambda: {"cost_total": 0.0, "total_tokens": 0, "turns": 0})

    for t in turns:
        ent = key_fn(t)
        bk = bucket_key(t["timestamp"], bucket)
        i = bucket_idx.get(bk)
        if i is None:
            continue
        matrix[ent][i] += t["cost_total"]
        s = summary[ent]
        s["cost_total"]   += t["cost_total"]
        s["total_tokens"] += t["total_tokens"]
        s["turns"]        += 1

    rows = []
    for ent, s in summary.items():
        rows.append({
            "entity":       ent,
            "label":        fmt_fn(ent),
            "values":       matrix[ent],
            "cost_total":   s["cost_total"],
            "total_tokens": s["total_tokens"],
            "turns":        s["turns"],
        })
    rows.sort(key=lambda r: -r["cost_total"])
    return buckets, rows, col_label

def show_trend(turns, dimension, since_ts, until_ts, bucket, top_n, label_cache=None):
    buckets, rows, col_label = build_trend(
        turns, dimension, since_ts, until_ts, bucket, label_cache
    )
    if not rows:
        print(f"  {GRY}No data.{R}")
        return

    label_w = max(len(r["label"]) for r in rows)
    label_w = max(label_w, len(col_label))
    spark_w = len(buckets)

    print(f"  {GRY}Buckets: {len(buckets)} × {bucket}  "
          f"({buckets[0]} → {buckets[-1]})  per-row scale{R}")
    print()
    print(f"  {BOLD}{col_label:<{label_w}}  {'COST':>10}  {'TURNS':>6}  "
          f"TREND{R}")
    print(f"  {'─'*label_w}  {'─'*10}  {'─'*6}  {'─'*spark_w}")

    for i, r in enumerate(rows):
        if i >= top_n:
            print(f"  {GRY}  … {len(rows) - top_n} more rows (use --top 0 to show all){R}")
            break
        row_max = max(r["values"]) if r["values"] else 0
        spark = sparkline(r["values"], row_max)
        print(f"  {CYN}{r['label']:<{label_w}}{R}  "
              f"{fmt_cost(r['cost_total']):>10}  "
              f"{GRY}{r['turns']:>6,}{R}  "
              f"{spark}")
    print()

# ── CSV / JSON output ─────────────────────────────────────────────────────────
def output_trend_csv(turns, dimension, since_ts, until_ts, bucket, label_cache=None):
    import csv, io
    out = io.StringIO()
    w = csv.writer(out)
    buckets, rows, col_label = build_trend(
        turns, dimension, since_ts, until_ts, bucket, label_cache
    )
    w.writerow([col_label.lower()] + buckets + ["cost_total", "total_tokens", "turns"])
    for r in rows:
        w.writerow(
            [r["label"]]
            + [round(v, 6) for v in r["values"]]
            + [round(r["cost_total"], 6), r["total_tokens"], r["turns"]]
        )
    print(out.getvalue(), end="")

def output_trend_json(turns, dimension, since_ts, until_ts, bucket, label_cache=None):
    buckets, rows, col_label = build_trend(
        turns, dimension, since_ts, until_ts, bucket, label_cache
    )
    payload = {
        "dimension":  dimension,
        "bucket":     bucket,
        "buckets":    buckets,
        "rows": [
            {
                "label":        r["label"],
                "values":       [round(v, 6) for v in r["values"]],
                "cost_total":   round(r["cost_total"], 6),
                "total_tokens": r["total_tokens"],
                "turns":        r["turns"],
            }
            for r in rows
        ],
    }
    print(json.dumps(payload, indent=2))

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
    p.add_argument("--trend",      nargs="?", const="agent",
                   choices=["agent", "model", "session"],
                   help="Time-series trend (default dimension: agent)")
    p.add_argument("--bucket",     choices=["hour", "day", "week", "auto"],
                   default="auto",
                   help="Bucket granularity for --trend / --by-day (default: auto)")
    p.add_argument("--top",        type=int, default=20,  help="Max rows per table (0 = all)")
    p.add_argument("--csv",        action="store_true",   help="CSV output")
    p.add_argument("--json",       action="store_true",   help="JSON output")
    p.add_argument("--no-colour",  action="store_true",   help="Disable colour output")
    args = p.parse_args()

    if args.no_colour or not sys.stdout.isatty():
        no_colour()

    # Determine time window
    now = datetime.now(timezone.utc)
    until_ts = now
    if args.all:
        since_ts = None
        period = "all time"
    elif args.today:
        since_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period = "today"
    else:
        since_ts = now - timedelta(days=args.days)
        period = f"last {args.days} days"

    # Resolve bucket granularity (used by --trend and trend exports)
    bucket = (
        auto_bucket(since_ts, until_ts, args.today)
        if args.bucket == "auto" else args.bucket
    )

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
    if args.trend:      modes.append("trend")
    if args.by_agent or not modes:
        modes = ["agent"] + [m for m in modes if m != "agent"]

    top_n = args.top if args.top > 0 else 9999
    needs_label_cache = ("session" in modes) or (args.trend == "session")

    # CSV / JSON fast paths
    if args.csv:
        if args.trend:
            label_cache = session_label_cache(AGENTS_DIR) if args.trend == "session" else None
            output_trend_csv(turns, args.trend, since_ts, until_ts, bucket, label_cache)
        else:
            output_csv(turns, modes[0])
        return
    if args.json:
        if args.trend:
            label_cache = session_label_cache(AGENTS_DIR) if args.trend == "session" else None
            output_trend_json(turns, args.trend, since_ts, until_ts, bucket, label_cache)
        else:
            output_json(turns, modes[0])
        return

    # Human-readable output
    agent_label = f" ({', '.join(sorted(agent_filter))})" if agent_filter else ""
    print_header(f"Usage report{agent_label}", period)

    t = totals(turns)
    print_totals_bar(t)

    # Build label cache only if needed
    label_cache = session_label_cache(AGENTS_DIR) if needs_label_cache else None

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
            show_by_session(turns, top_n=top_n, label_cache=label_cache)
        elif mode == "trend":
            print(f"  {BOLD}Trend by {args.trend}:{R}")
            show_trend(turns, args.trend, since_ts, until_ts, bucket,
                       top_n=top_n, label_cache=label_cache)

    print(f"  {GRY}Run with --by-model, --by-day, --by-session, --trend for more breakdowns.{R}")
    print(f"  {GRY}Use --csv or --json for machine-readable output.{R}\n")

if __name__ == "__main__":
    main()
