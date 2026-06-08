#!/usr/bin/env python3
"""
ochealth — OpenClaw gateway health snapshot

Single-command view of gateway status, active agents, connected channels,
models, and recent sessions.

Usage:
  python3 ochealth.py                # full summary
  python3 ochealth.py --agents       # just agent list with last-seen
  python3 ochealth.py --channels     # connected channels
  python3 ochealth.py --sessions     # recent sessions
  python3 ochealth.py --models       # configured models
  python3 ochealth.py --tasks        # task queue status
  python3 ochealth.py --json         # machine-readable output
  python3 ochealth.py --no-color     # disable ANSI colors
"""

import os, sys, json, subprocess, argparse
from datetime import datetime, timezone

# ── ANSI ─────────────────────────────────────────────────────────────────────
R    = "\033[0m"
BOLD = "\033[1m"
DIM  = "\033[2m"
RED  = "\033[31m"
GRN  = "\033[32m"
YLW  = "\033[33m"
BLU  = "\033[34m"
MAG  = "\033[35m"
CYN  = "\033[36m"
WHT  = "\033[37m"
GRY  = "\033[90m"

def no_colour():
    global R, BOLD, DIM, RED, GRN, YLW, BLU, MAG, CYN, WHT, GRY
    R = BOLD = DIM = RED = GRN = YLW = BLU = MAG = CYN = WHT = GRY = ""

# ── CLI helpers ──────────────────────────────────────────────────────────────

def run_cli(*args):
    """Run an openclaw CLI command and return parsed JSON, or None on failure."""
    try:
        result = subprocess.run(
            ["openclaw", *args, "--json"],
            capture_output=True, text=True, timeout=15
        )
        # openclaw prints warnings to stderr; JSON is on stdout
        if result.returncode != 0 and not result.stdout.strip():
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None

def age_str(ms):
    """Format a millisecond age into a human-readable string."""
    if ms is None:
        return "never"
    secs = ms / 1000
    if secs < 60:
        return f"{int(secs)}s ago"
    if secs < 3600:
        return f"{int(secs/60)}m ago"
    if secs < 86400:
        return f"{secs/3600:.1f}h ago"
    return f"{secs/86400:.1f}d ago"

def ts_str(epoch_ms):
    """Format epoch millis to local time string."""
    if not epoch_ms:
        return "—"
    dt = datetime.fromtimestamp(epoch_ms / 1000)
    return dt.strftime("%H:%M:%S")

def health_dot(ok):
    if ok:
        return f"{GRN}●{R}"
    return f"{RED}●{R}"

# ── Data collection ──────────────────────────────────────────────────────────

def collect():
    """Gather all health data from openclaw CLI."""
    data = {}
    data["status"] = run_cli("status")
    data["channels"] = run_cli("channels", "status")
    data["models"] = run_cli("models", "status")
    return data

# ── Renderers ────────────────────────────────────────────────────────────────

def render_gateway(status):
    gw = status.get("gateway", {})
    svc = status.get("gatewayService", {})
    os_info = status.get("os", {})

    reachable = gw.get("reachable", False)
    latency = gw.get("connectLatencyMs")
    self_info = gw.get("self", {})

    print(f"{BOLD}Gateway{R}")
    print(f"  {health_dot(reachable)} {'Reachable' if reachable else 'Unreachable'}", end="")
    if latency:
        print(f" {GRY}({latency}ms){R}", end="")
    print()
    print(f"  URL:      {gw.get('url', '?')}")
    print(f"  Host:     {self_info.get('host', '?')} ({self_info.get('ip', '?')})")
    print(f"  Version:  {status.get('runtimeVersion', '?')} · {self_info.get('platform', '?')}")
    print(f"  Service:  {'loaded' if svc.get('loaded') else 'not loaded'}", end="")
    runtime = svc.get("runtimeShort", "")
    if runtime:
        print(f" · {runtime}", end="")
    print()
    print()

def render_agents(status):
    agents_data = status.get("agents", {})
    agents = agents_data.get("agents", [])
    total_sessions = agents_data.get("totalSessions", 0)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    print(f"{BOLD}Agents{R} {GRY}({len(agents)} agents, {total_sessions} total sessions){R}")

    # Sort by last active (most recent first), filter out ch-* agents for cleaner view
    named = [a for a in agents if not a["id"].startswith("ch-")]
    channel_agents = [a for a in agents if a["id"].startswith("ch-")]

    for a in sorted(named, key=lambda x: x.get("lastUpdatedAt") or 0, reverse=True):
        aid = a["id"]
        name = a.get("name", aid)
        sessions = a.get("sessionsCount", 0)
        age_ms = a.get("lastActiveAgeMs")

        # Color by recency
        if age_ms is not None and age_ms < 300_000:  # < 5 min
            dot = f"{GRN}●{R}"
            age_col = GRN
        elif age_ms is not None and age_ms < 3600_000:  # < 1 hour
            dot = f"{YLW}●{R}"
            age_col = YLW
        else:
            dot = f"{GRY}●{R}"
            age_col = GRY

        label = f"{BOLD}{name}{R}" if name != aid else name
        if name != aid:
            label += f" {GRY}({aid}){R}"

        print(f"  {dot} {label}  {GRY}{sessions} sessions{R}  {age_col}{age_str(age_ms)}{R}")

    if channel_agents:
        active_ch = [a for a in channel_agents if a.get("lastActiveAgeMs") is not None and a["lastActiveAgeMs"] < 3600_000]
        idle_ch = len(channel_agents) - len(active_ch)
        if active_ch:
            print(f"  {GRY}+ {len(active_ch)} active channel agent(s), {idle_ch} idle{R}")
        else:
            print(f"  {GRY}+ {len(channel_agents)} channel agent(s) (all idle){R}")
    print()

def render_channels(channels_data):
    if not channels_data:
        print(f"{BOLD}Channels{R}")
        print(f"  {RED}● Could not fetch channel status{R}")
        print()
        return

    channels = channels_data.get("channels", {})
    accounts = channels_data.get("channelAccounts", {})
    event_loop = channels_data.get("eventLoop", {})

    print(f"{BOLD}Channels{R}")

    for ch_id, ch in channels.items():
        running = ch.get("running", False)
        configured = ch.get("configured", False)
        print(f"  {health_dot(running)} {ch_id.capitalize()}  {'running' if running else 'stopped'}")

        # Show accounts for this channel
        ch_accounts = accounts.get(ch_id, [])
        for acc in ch_accounts:
            connected = acc.get("connected", False)
            health = acc.get("healthState", "unknown")
            name = acc.get("name") or acc.get("accountId", "?")
            last_in = acc.get("lastInboundAt")
            last_out = acc.get("lastOutboundAt")

            if connected and health == "healthy":
                acc_dot = f"{GRN}·{R}"
            elif connected:
                acc_dot = f"{YLW}·{R}"
            else:
                acc_dot = f"{RED}·{R}"

            parts = [f"    {acc_dot} {name}"]
            if last_in:
                parts.append(f"in:{ts_str(last_in)}")
            if last_out:
                parts.append(f"out:{ts_str(last_out)}")
            if acc.get("reconnectAttempts", 0) > 0:
                parts.append(f"{YLW}reconnecting({acc['reconnectAttempts']}){R}")
            print("  ".join(parts))

    if event_loop:
        degraded = event_loop.get("degraded", False)
        util = event_loop.get("utilization", 0)
        interval = event_loop.get("intervalMs", 0)
        p99 = event_loop.get("delayP99Ms", 0)
        if degraded:
            print(f"  {RED}Event loop degraded: {', '.join(event_loop.get('reasons', []))}{R}")
        else:
            print(f"  {GRY}Event loop: {interval/1000:.1f}s interval, p99 {p99:.0f}ms, {util*100:.1f}% util{R}")
    print()

def render_models(models_data):
    if not models_data:
        print(f"{BOLD}Models{R}")
        print(f"  {RED}● Could not fetch model status{R}")
        print()
        return

    default = models_data.get("defaultModel", "?")
    aliases = models_data.get("aliases", {})
    allowed = models_data.get("allowed", [])
    auth = models_data.get("auth", {})
    providers = auth.get("providers", []) if isinstance(auth, dict) else []

    print(f"{BOLD}Models{R}")
    print(f"  Default: {CYN}{default}{R}")

    if aliases:
        alias_strs = [f"{k}={v.split('/')[-1]}" for k, v in aliases.items()]
        print(f"  Aliases: {GRY}{', '.join(alias_strs)}{R}")

    # Provider auth status
    for p in providers:
        if not isinstance(p, dict):
            continue
        provider = p.get("provider", "?")
        eff = p.get("effective", {})
        kind = eff.get("kind", "?")
        profile_count = len(p.get("profiles", []))
        missing = p.get("missingInUse", [])
        if missing:
            print(f"  {health_dot(False)} {provider} {GRY}({kind}){R} {RED}missing: {', '.join(missing)}{R}")
        else:
            print(f"  {health_dot(True)} {provider} {GRY}({kind}, {profile_count} profiles){R}")

    if allowed:
        print(f"  {GRY}Allowed: {len(allowed)} models{R}")
    print()

def render_sessions(status):
    sessions = status.get("sessions", {})
    recent = sessions.get("recent", [])
    count = sessions.get("count", 0)
    defaults = sessions.get("defaults", {})

    print(f"{BOLD}Sessions{R} {GRY}({count} total, default {defaults.get('model', '?')}){R}")

    for s in recent[:8]:
        agent = s.get("agentId", "?")
        kind = s.get("kind", "?")
        age_ms = s.get("age")
        model = (s.get("model") or "?").split("/")[-1]
        inp = s.get("inputTokens", 0)
        out = s.get("outputTokens", 0)
        ctx = s.get("contextTokens", 0)
        cached = s.get("cachedRatio")

        # Color by kind
        kind_col = {
            "direct": CYN, "group": BLU, "cron": MAG,
            "spawn-child": YLW, "spawn": YLW
        }.get(kind, GRY)

        pct = f"{inp/ctx*100:.0f}%" if ctx > 0 else "?"
        cache_str = f" {GRY}{cached*100:.0f}% cached{R}" if cached else ""

        # Truncate agent for display
        display_agent = agent[:20] if len(agent) > 20 else agent

        # age field from openclaw is in milliseconds
        print(f"  {kind_col}{kind:12s}{R} {display_agent:20s} {model:22s} {pct:>4s} ctx{cache_str}  {GRY}{age_str(age_ms)}{R}")
    print()

def render_tasks(status):
    tasks = status.get("tasks", {})
    total = tasks.get("total", 0)
    active = tasks.get("active", 0)
    by_status = tasks.get("byStatus", {})
    by_runtime = tasks.get("byRuntime", {})

    print(f"{BOLD}Tasks{R} {GRY}({total} total, {active} active){R}")

    running = by_status.get("running", 0)
    queued = by_status.get("queued", 0)
    failed = by_status.get("failed", 0)
    succeeded = by_status.get("succeeded", 0)

    parts = []
    if running:
        parts.append(f"{GRN}{running} running{R}")
    if queued:
        parts.append(f"{YLW}{queued} queued{R}")
    if succeeded:
        parts.append(f"{GRY}{succeeded} succeeded{R}")
    if failed:
        parts.append(f"{RED}{failed} failed{R}")
    print(f"  {' · '.join(parts)}")

    if by_runtime:
        rt_parts = [f"{v} {k}" for k, v in by_runtime.items() if v > 0]
        print(f"  {GRY}By runtime: {', '.join(rt_parts)}{R}")

    # Task audit
    audit = status.get("taskAudit", {})
    warnings = audit.get("warnings", 0)
    errors = audit.get("errors", 0)
    if warnings or errors:
        print(f"  Audit: {YLW}{warnings} warnings{R}, {RED}{errors} errors{R}")
    print()

# ── JSON output ──────────────────────────────────────────────────────────────

def output_json(data):
    """Combine all collected data into a single JSON snapshot."""
    status = data.get("status") or {}
    channels = data.get("channels") or {}
    models = data.get("models") or {}

    out = {
        "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
        "version": status.get("runtimeVersion"),
        "gateway": status.get("gateway"),
        "service": status.get("gatewayService"),
        "os": status.get("os"),
        "agents": status.get("agents"),
        "sessions": status.get("sessions"),
        "tasks": status.get("tasks"),
        "taskAudit": status.get("taskAudit"),
        "heartbeat": status.get("heartbeat"),
        "channels": channels.get("channels"),
        "channelAccounts": channels.get("channelAccounts"),
        "eventLoop": channels.get("eventLoop"),
        "models": {
            "default": models.get("defaultModel"),
            "aliases": models.get("aliases"),
            "allowed": models.get("allowed"),
            "auth": models.get("auth"),
        } if models else None,
    }
    print(json.dumps(out, indent=2))

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw gateway health snapshot"
    )
    parser.add_argument("--agents", action="store_true", help="Show agents only")
    parser.add_argument("--channels", action="store_true", help="Show channels only")
    parser.add_argument("--sessions", action="store_true", help="Show recent sessions only")
    parser.add_argument("--models", action="store_true", help="Show models only")
    parser.add_argument("--tasks", action="store_true", help="Show tasks only")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        no_colour()

    # Collect data
    data = collect()
    status = data.get("status")

    if not status:
        print(f"{RED}Could not reach OpenClaw gateway.{R}")
        print(f"Is it running? Try: openclaw gateway run")
        sys.exit(1)

    if args.json:
        output_json(data)
        return

    # Section filter
    show_all = not (args.agents or args.channels or args.sessions or args.models or args.tasks)

    print()
    print(f"{BOLD}{CYN}ochealth{R} {GRY}— OpenClaw {status.get('runtimeVersion', '?')}{R}")
    print()

    if show_all or args.agents:
        render_gateway(status)
    if show_all or args.agents:
        render_agents(status)
    if show_all or args.channels:
        render_channels(data.get("channels"))
    if show_all or args.models:
        render_models(data.get("models"))
    if show_all or args.sessions:
        render_sessions(status)
    if show_all or args.tasks:
        render_tasks(status)

if __name__ == "__main__":
    main()
