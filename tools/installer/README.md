# installer

Native macOS installer wizard for OpenClaw. SwiftUI app that walks users through a complete installation without requiring Terminal knowledge.

**Status:** Early development — not yet ready for public use.

## What it does

1. Installs prerequisites (Node.js, Git) automatically
2. Installs OpenClaw
3. Configures your AI model provider and API key
4. Connects your first chat channel (Telegram or Slack)
5. Launches OpenClaw and confirms everything works

## Building

Requires Xcode 15+, macOS 13+, and an Apple Developer account for signing.

```bash
open LobKit.xcodeproj
```

## Architecture

- Native SwiftUI (no Electron, no web views)
- Backend driven by `openclaw config patch` + `openclaw gateway install`
- Signed with Apple Developer ID

## License

MIT
