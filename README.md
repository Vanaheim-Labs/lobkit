# LobKit

Power tools for [OpenClaw](https://openclaw.ai).

A collection of utilities that give you more visibility, control, and power over your OpenClaw setup. No fluff — just sharp tools that solve real problems.

## Tools

| Tool | What it does | Install |
|------|-------------|---------|
| **[ocwatch](tools/ocwatch/)** | Real-time session activity monitor — stream all agent activity from the terminal | `curl -sL lobkit.com/ocwatch \| bash` |
| **[ocbudget](tools/ocbudget/)** | Cost and token tracker — see exactly what you're spending by agent, model, or day | `curl -fsSL lobkit.com/ocbudget -o ocbudget.py` |
| **[installer](tools/installer/)** | Native macOS installer wizard for OpenClaw (SwiftUI) | Build from Xcode |

## Philosophy

- **Unix-style**: each tool does one thing well
- **No dependencies**: pure Python / native Swift — no npm, no pip, no Docker
- **Terminal-first**: if it can be a CLI, it is a CLI
- **OpenClaw-native**: built around OpenClaw's file layout and conventions

## Quick Start

```bash
# Install ocwatch (the session watcher)
curl -sL lobkit.com/ocwatch | bash

# Or clone the whole toolkit
git clone https://github.com/Vanaheim-Labs/lobkit.git
```

## Contributing

PRs welcome. Each tool lives in `tools/<name>/` with its own README and install script.

## License

MIT
