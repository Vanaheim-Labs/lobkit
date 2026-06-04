# ocwatch

Real-time session activity monitor for OpenClaw. Like `tail -f` for your agents.

Streams all agent session activity — user messages, assistant responses, tool calls, results, and thinking blocks — with colour-coded, formatted output.

## Install

```bash
curl -sL lobkit.com/ocwatch | bash
```

Or manually:
```bash
cp tools/ocwatch/ocwatch.py ~/.openclaw/bin/ocwatch
chmod +x ~/.openclaw/bin/ocwatch
```

## Usage

```bash
ocwatch                          # all agents, last 24h
ocwatch -v --tail 20             # verbose + replay last 20 lines (recommended)
ocwatch themis ed sif            # specific agents only
ocwatch --hours 2                # only sessions from last 2h
ocwatch --raw                    # raw JSON (pipe to jq)
ocwatch --all                    # all sessions regardless of age
```

## What you see

```
ocwatch — all agents  [last 24h]  (Ctrl-C to exit)
────────────────────────────────────────────────────────────────────
14:23:01  themis 3a8f2c01  new session  3a8f2c01-...
14:23:01  themis 3a8f2c01  ▶ user   Can you fix the login bug?
14:23:03  themis 3a8f2c01  ◀ asst   Let me look at the auth code.
14:23:04  themis 3a8f2c01  ⚙ Read   src/auth/login.ts
14:23:04  themis 3a8f2c01    └─ result  export function login(...
14:23:06  themis 3a8f2c01  ⚙ Edit   src/auth/login.ts
14:23:06  themis 3a8f2c01  ◀ asst   Fixed — the session token wasn't being set.
```

Each agent gets a persistent colour. Sessions get distinct background tints so interleaved activity is easy to follow.

## Symbols

| Symbol | Meaning |
|--------|---------|
| `▶ user` | User message |
| `◀ asst` | Assistant response |
| `⚙ Tool` | Tool call (shows key argument) |
| `└─ result` | Tool result |
| `💭` | Thinking block (verbose mode) |
| `▷` | Session start |
| `■` | Session end |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--verbose` / `-v` | off | Show thinking blocks and model changes |
| `--tail N` | 0 | Replay last N lines of each session on start |
| `--hours N` | 24 | Only watch sessions modified within N hours |
| `--all` | off | Watch all sessions regardless of age |
| `--raw` | off | Output raw JSON lines (for piping) |
| `--poll N` | 0.4 | Polling interval in seconds |

## Requirements

- Python 3.8+
- OpenClaw installed (reads from `~/.openclaw/agents/*/sessions/*.jsonl`)
- A terminal that supports ANSI colours (any modern terminal)

## How it works

ocwatch tails the plain `.jsonl` session files that OpenClaw writes for each agent session. It polls for new files and new lines, parses each JSON event, and renders it with colour-coded formatting. No network calls, no dependencies — just file I/O.

## License

MIT
