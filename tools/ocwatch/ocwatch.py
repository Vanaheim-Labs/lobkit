#!/usr/bin/env python3
"""
ocwatch — OpenClaw session activity watcher
Streams all agent session activity in real time.

Uses the plain .jsonl session files (not .trajectory.jsonl) which contain
the full message history: user input, assistant text, tool calls, tool results,
and thinking blocks.

Usage:
  python3 ocwatch.py                    # watch all agents, last 24h
  python3 ocwatch.py sif ed themis      # specific agents only
  python3 ocwatch.py --hours 2          # only sessions from last 2h
  python3 ocwatch.py --tail 50          # replay last 50 lines of each file on start
  python3 ocwatch.py --all              # all sessions regardless of age
  python3 ocwatch.py --raw              # raw JSON lines
  python3 ocwatch.py -v                 # verbose (include thinking blocks)
"""

import os, sys, json, time, argparse, glob
from datetime import datetime

AGENTS_DIR = os.path.expanduser("~/.openclaw/agents")

# ── ANSI ─────────────────────────────────────────────────────────────────────
R   = "\033[0m"
BOLD= "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GRN = "\033[32m"
YLW = "\033[33m"
BLU = "\033[34m"
MAG = "\033[35m"
CYN = "\033[36m"
WHT = "\033[37m"
GRY = "\033[90m"

AGENT_PALETTE = [CYN, GRN, MAG, YLW, BLU, RED, WHT]
_colour_map = {}
_colour_idx = 0

def agent_colour(name):
    global _colour_idx
    if name not in _colour_map:
        _colour_map[name] = AGENT_PALETTE[_colour_idx % len(AGENT_PALETTE)]
        _colour_idx += 1
    return _colour_map[name]

# ── Session-level colour coding ──────────────────────────────────────────────
# Each unique session ID gets a distinct 256-colour background tint so
# interleaved sessions from the same agent are visually separable.
# We use subtle background colours that work on dark terminals.
SESSION_BG_PALETTE = [
    "\033[48;5;236m",  # dark grey
    "\033[48;5;17m",   # very dark blue
    "\033[48;5;52m",   # very dark red
    "\033[48;5;22m",   # very dark green
    "\033[48;5;53m",   # very dark magenta
    "\033[48;5;58m",   # dark olive
    "\033[48;5;23m",   # dark teal
    "\033[48;5;94m",   # dark orange/brown
    "\033[48;5;238m",  # slightly lighter grey
    "\033[48;5;18m",   # navy
    "\033[48;5;54m",   # purple
    "\033[48;5;24m",   # steel blue
]

# Map of full session id → tag colour (bg pill + contrasting fg for readability)
SESSION_TAG_PALETTE = [
    "\033[48;5;25m\033[38;5;153m",   # blue bg, light blue fg
    "\033[48;5;94m\033[38;5;222m",   # brown bg, amber fg
    "\033[48;5;22m\033[38;5;150m",   # green bg, sage fg
    "\033[48;5;52m\033[38;5;217m",   # red bg, salmon fg
    "\033[48;5;54m\033[38;5;183m",   # purple bg, lavender fg
    "\033[48;5;58m\033[38;5;187m",   # olive bg, cream fg
    "\033[48;5;88m\033[38;5;174m",   # dark red bg, dusty rose fg
    "\033[48;5;23m\033[38;5;116m",   # teal bg, light teal fg
    "\033[48;5;130m\033[38;5;223m",  # dark orange bg, peach fg
    "\033[48;5;17m\033[38;5;111m",   # navy bg, periwinkle fg
    "\033[48;5;53m\033[38;5;218m",   # magenta bg, pink fg
    "\033[48;5;28m\033[38;5;114m",   # forest bg, fern fg
]
_session_colour_map = {}
_session_colour_idx = 0

def session_tag_colour(sid):
    """Return a distinct 256-colour foreground code for this session id."""
    global _session_colour_idx
    if sid not in _session_colour_map:
        _session_colour_map[sid] = SESSION_TAG_PALETTE[_session_colour_idx % len(SESSION_TAG_PALETTE)]
        _session_colour_idx += 1
    return _session_colour_map[sid]

def trunc(s, n=220):
    s = str(s).strip()
    # collapse newlines to spaces for single-line display
    s = " ".join(s.split())
    return s[:n] + "…" if len(s) > n else s

def ts():
    return datetime.now().strftime("%H:%M:%S")

def short(sid, n=8):
    return sid[:n] if sid else "?"

def agent_label(agent, sid):
    col = agent_colour(agent)
    stag = session_tag_colour(sid)
    return f"{col}{BOLD}{agent}{R} {stag} {short(sid)} {R}"

# ── Session tracking for legend ───────────────────────────────────────────────
_seen_sessions = set()

def maybe_print_session_legend(agent, sid):
    """Print a coloured legend line when a session is first seen."""
    key = f"{agent}:{sid}"
    if key not in _seen_sessions:
        _seen_sessions.add(key)
        col = agent_colour(agent)
        stag = session_tag_colour(sid)
        pill = f"{stag} {short(sid)} {R}"
        print(f"{GRY}{ts()}{R} {pill} {col}{BOLD}{agent}{R} {GRY}new session{R} {DIM}{sid}{R}")
        sys.stdout.flush()

# ── Render a single message event ─────────────────────────────────────────────
def render_message(agent, sid, ev, args):
    msg  = ev.get("message", {})
    role = msg.get("role", "?")
    content = msg.get("content", "")
    label = agent_label(agent, sid)
    now   = ts()
    lines = []

    if isinstance(content, str):
        if content.strip() and role == "user":
            lines.append(f"{GRY}{now}{R} {label} {BOLD}▶ user{R}   {trunc(content, 300)}")
        return lines

    if not isinstance(content, list):
        return lines

    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type", "")

        if ptype == "text":
            text = part.get("text", "").strip()
            if not text:
                continue
            if role == "user":
                col = agent_colour(agent)
                lines.append(f"{GRY}{now}{R} {label} {BOLD}▶ user{R}   {trunc(text, 300)}")
            elif role == "assistant":
                col = agent_colour(agent)
                lines.append(f"{GRY}{now}{R} {label} {col}{BOLD}◀ asst{R}   {trunc(text, 300)}")

        elif ptype in ("tool_use", "toolCall"):
            name = part.get("name", "?")
            inp  = part.get("input", part.get("arguments", {}))
            # Show key arg concisely
            if isinstance(inp, dict):
                if "command" in inp:
                    inp_s = trunc(inp["command"], 200)
                elif "file_path" in inp:
                    inp_s = inp["file_path"]
                elif "pattern" in inp:
                    inp_s = inp["pattern"]
                elif "query" in inp:
                    inp_s = trunc(str(inp["query"]), 200)
                else:
                    inp_s = json.dumps(inp, separators=(",", ":"))
                    inp_s = trunc(inp_s, 200)
            else:
                inp_s = trunc(str(inp), 200)
            lines.append(f"{GRY}{now}{R} {label} {YLW}⚙ {BOLD}{name}{R}{YLW}  {inp_s}{R}")

        elif ptype in ("tool_result", "toolResult"):
            result_content = part.get("content", "")
            if isinstance(result_content, list):
                result_content = " ".join(
                    p.get("text", "") for p in result_content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            lines.append(f"{GRY}{now}{R} {label} {GRY}  └─ result  {trunc(str(result_content), 200)}{R}")

        elif ptype == "thinking":
            think = part.get("text", part.get("thinking", "")).strip()
            if think:
                lines.append(f"{GRY}{now}{R} {label} {DIM}  💭 {trunc(think, 200)}{R}")

    # tool results are role=toolResult (OpenClaw-specific role)
    if role == "toolResult":
        text = ""
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text += part.get("text", "")
        elif isinstance(content, str):
            text = content
        if text.strip():
            lines.append(f"{GRY}{now}{R} {label} {GRY}  └─ result  {trunc(text, 200)}{R}")

    return lines

def render_event(agent, sid, ev, args):
    if args.raw:
        print(json.dumps(ev))
        sys.stdout.flush()
        return

    # Print a coloured legend entry the first time we see this session
    maybe_print_session_legend(agent, sid)

    t = ev.get("type", "?")
    label = agent_label(agent, sid)
    now = ts()

    if t == "message":
        for line in render_message(agent, sid, ev, args):
            print(line)
        sys.stdout.flush()

    elif t == "session":
        # OpenClaw session entries have type="session" (start) with id/version/cwd
        sid_val = ev.get("id", "")[:12]
        print(f"{GRY}{now}{R} {label} {GRN}▷ session start{R} {GRY}{sid_val}{R}")
        sys.stdout.flush()

    elif t == "session.started":
        model = ev.get("modelId", "")
        sid_val = ev.get("sessionId", "")[:12]
        print(f"{GRY}{now}{R} {label} {GRN}▷ session start{R} {GRY}{sid_val} model={model}{R}")
        sys.stdout.flush()

    elif t in ("session.ended", "session_end"):
        print(f"{GRY}{now}{R} {label} {GRY}■ session end{R}")
        sys.stdout.flush()

    elif t == "custom_message":
        # Usually delivery confirmations, errors etc.
        data = ev.get("message", ev)
        text = str(data)
        if "error" in text.lower():
            print(f"{GRY}{now}{R} {label} {RED}✗ {trunc(text, 200)}{R}")
            sys.stdout.flush()
        elif args.verbose:
            print(f"{GRY}{now}{R} {label} {DIM}custom: {trunc(text, 160)}{R}")
            sys.stdout.flush()

    elif t == "model_change":
        model = ev.get("modelId", ev.get("model", "?"))
        print(f"{GRY}{now}{R} {label} {GRY}model → {model}{R}")
        sys.stdout.flush()

    elif t == "thinking_level_change" and args.verbose:
        level = ev.get("thinkingLevel", "?")
        print(f"{GRY}{now}{R} {label} {DIM}thinking={level}{R}")
        sys.stdout.flush()
        sys.stdout.flush()


# ── File tailer ───────────────────────────────────────────────────────────────
class Tailer:
    def __init__(self, path, agent, sid, args):
        self.path   = path
        self.agent  = agent
        self.sid    = sid
        self.args   = args
        self._fh    = None
        self._pos   = 0

    def open(self, replay_lines=0):
        try:
            self._fh = open(self.path, "r", encoding="utf-8", errors="replace")
            if replay_lines > 0:
                # read last N lines then position there
                all_lines = self._fh.readlines()
                tail = all_lines[-replay_lines:]
                for line in tail:
                    self._parse_line(line)
                self._pos = self._fh.tell()
            else:
                self._fh.seek(0, 2)
                self._pos = self._fh.tell()
        except OSError:
            pass

    def _parse_line(self, line):
        line = line.strip()
        if not line:
            return
        try:
            ev = json.loads(line)
            render_event(self.agent, self.sid, ev, self.args)
        except json.JSONDecodeError:
            pass

    def poll(self):
        if not self._fh:
            return
        try:
            self._fh.seek(self._pos)
            for line in self._fh:
                self._parse_line(line)
            self._pos = self._fh.tell()
        except OSError:
            pass

    def close(self):
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass


# ── File discovery ────────────────────────────────────────────────────────────
def agent_from_path(path):
    rel = path.replace(AGENTS_DIR, "").lstrip("/")
    return rel.split("/")[0]

def sid_from_path(path):
    base = os.path.basename(path)
    # strip known suffixes
    for suf in (".trajectory.jsonl", ".jsonl"):
        if base.endswith(suf):
            base = base[:-len(suf)]
            break
    return base

def discover(filter_agents, args):
    # Use plain .jsonl files — they have the full message content
    all_files = glob.glob(os.path.join(AGENTS_DIR, "*", "sessions", "*.jsonl"))
    # Exclude trajectory files
    files = [f for f in all_files if not f.endswith(".trajectory.jsonl")
             and not f.endswith(".trajectory-path.json")]

    if filter_agents:
        low = [a.lower() for a in filter_agents]
        files = [f for f in files if agent_from_path(f).lower() in low]

    if not args.watch_all:
        cutoff = time.time() - args.hours * 3600
        files = [f for f in files if os.path.getmtime(f) >= cutoff]

    return files


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="OpenClaw session activity watcher")
    p.add_argument("agents", nargs="*", help="Agent names to watch (default: all)")
    p.add_argument("--raw",     action="store_true", help="Raw JSON output")
    p.add_argument("--verbose", "-v", action="store_true", help="Include thinking + model changes")
    p.add_argument("--poll",    type=float, default=0.4, help="Poll interval seconds (default 0.4)")
    p.add_argument("--hours",   type=float, default=24.0, help="Watch files modified within N hours (default 24)")
    p.add_argument("--tail",    type=int,   default=0, help="Replay last N lines of each file on start")
    p.add_argument("--all",     dest="watch_all", action="store_true", help="Watch all files regardless of age")
    args = p.parse_args()

    filter_agents = args.agents
    known = set()
    tailers = {}

    if not args.raw:
        age_label = "all time" if args.watch_all else f"last {args.hours:.0f}h"
        label = ", ".join(filter_agents) if filter_agents else "all agents"
        print(f"{BOLD}ocwatch{R} — {CYN}{label}{R}  {GRY}[{age_label}]  (Ctrl-C to exit){R}")
        print(f"{GRY}{'─' * 68}{R}")
        sys.stdout.flush()

    try:
        while True:
            current = set(discover(filter_agents, args))
            new = current - known
            if new and not args.raw:
                agents_in_batch = set()
                for f in sorted(new):
                    agents_in_batch.add(agent_from_path(f))
                if not tailers:
                    # First discovery — summarise instead of listing every file
                    print(f"{GRY}{ts()}{R} {GRN}tracking{R} {len(new)} session(s) across {len(agents_in_batch)} agent(s): {', '.join(sorted(agents_in_batch))}")
                else:
                    # New files appearing during watch — show individually
                    for f in sorted(new):
                        ag = agent_from_path(f)
                        col = agent_colour(ag)
                        print(f"{GRY}{ts()}{R} {GRN}+ new{R} {col}{BOLD}{ag}{R}{GRY}[{short(sid_from_path(f))}]{R}")
                sys.stdout.flush()

            for f in sorted(new):
                ag  = agent_from_path(f)
                sid = sid_from_path(f)
                t   = Tailer(f, ag, sid, args)
                t.open(replay_lines=args.tail)
                tailers[f] = t
                known.add(f)

            for t in tailers.values():
                t.poll()

            time.sleep(args.poll)

    except KeyboardInterrupt:
        if not args.raw:
            print(f"\n{GRY}ocwatch stopped.{R}")
        for t in tailers.values():
            t.close()

if __name__ == "__main__":
    main()
