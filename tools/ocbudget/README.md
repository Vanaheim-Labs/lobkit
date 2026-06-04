# 💸 ocbudget

**Cost and token tracker for OpenClaw.**

Parses your session files and tells you exactly what you're spending — broken down by agent, model, or day. Zero dependencies, works offline, reads the same `.jsonl` files OpenClaw writes naturally.

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Vanaheim-Labs/lobkit/main/tools/ocbudget/ocbudget.py -o ocbudget.py
```

Requires Python 3.7+. No dependencies beyond the standard library.

---

## Usage

```bash
# Last 30 days, by agent (default)
python3 ocbudget.py

# Last 7 days
python3 ocbudget.py --days 7

# Today only
python3 ocbudget.py --today

# All time
python3 ocbudget.py --all

# Break down by model instead of agent
python3 ocbudget.py --by-model

# Break down by day
python3 ocbudget.py --by-day

# Most expensive individual sessions
python3 ocbudget.py --by-session

# Combine breakdowns
python3 ocbudget.py --days 7 --by-agent --by-model --by-day

# Specific agents only
python3 ocbudget.py themis sif

# Machine-readable output
python3 ocbudget.py --csv > budget.csv
python3 ocbudget.py --json | jq .
```

---

## Example output

```
────────────────────────────────────────────────────────────────────────
  💸 ocbudget  —  Usage report  last 7 days
────────────────────────────────────────────────────────────────────────

  Total cost:    $1,179.24  (917.17M tokens, 14,364 turns)
    ├ input:       $0.10  (40.9K)
    ├ output:      $48.80  (3.39M)
    ├ cache read:  $186.85  (646.35M)
    └ cache write: $943.49  (272.88M)

  By agent:
  AGENT                 COST    TOKENS   TURNS  BREAKDOWN
  ──────────────  ──────────  ────────  ──────  ────────────────────
  themis             $349.72   490.40M   6,007  ████████████████████
  kern               $161.86    45.86M     318  █████████░░░░░░░░░░░
  swift              $105.17   119.81M   1,518  ██████░░░░░░░░░░░░░░
  ...
```

---

## Flags reference

| Flag | Default | Description |
|------|---------|-------------|
| `--days N` | 30 | Look back N days |
| `--today` | — | Today only |
| `--all` | — | All time |
| `--by-agent` | ✓ | Break down by agent |
| `--by-model` | — | Break down by model |
| `--by-day` | — | Break down by day (chronological) |
| `--by-session` | — | Most expensive sessions |
| `--top N` | 20 | Max rows per table (0 = all) |
| `--csv` | — | CSV output |
| `--json` | — | JSON output |
| `--no-colour` | — | Disable ANSI colour |
| `[agent ...]` | all | Filter to named agents |

---

## How it works

ocbudget reads OpenClaw's `.jsonl` session files from `~/.openclaw/agents/*/sessions/`. Every assistant turn includes a `usage` block with pre-calculated token counts and costs per category (input, output, cache read, cache write). ocbudget aggregates these across all turns in the time window and presents them grouped however you ask.

Cache costs dominate on long-running agents — the breakdown shows exactly why.

---

*Part of [LobKit](../../README.md) — power tools for OpenClaw users.*
