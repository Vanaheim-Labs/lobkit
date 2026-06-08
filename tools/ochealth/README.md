# ochealth

Single-command OpenClaw gateway health snapshot.

Shows gateway status, active agents, connected channels, configured models, recent sessions, and task queue state.

## Usage

```bash
python3 ochealth.py                # full summary
python3 ochealth.py --agents       # agents + gateway only
python3 ochealth.py --channels     # connected channels
python3 ochealth.py --sessions     # recent sessions
python3 ochealth.py --models       # configured models + provider auth
python3 ochealth.py --tasks        # task queue status
python3 ochealth.py --json         # machine-readable JSON output
python3 ochealth.py --no-color     # disable ANSI colors
```

## Requirements

- Python 3.9+
- `openclaw` CLI in PATH
- No external dependencies (stdlib only)

## Install

```bash
# Option 1: symlink into PATH
ln -s "$(pwd)/ochealth.py" ~/.openclaw/bin/ochealth

# Option 2: just run it
python3 ~/.openclaw/workspace/lobkit/tools/ochealth/ochealth.py
```

## Output

Agents are color-coded by recency: green (< 5 min), yellow (< 1 hour), grey (older). Channel accounts show connection health and last inbound/outbound timestamps. Sessions show context utilization and cache ratios.

`--json` produces a single JSON object combining gateway, agent, channel, model, session, and task data — useful for monitoring or dashboards.
