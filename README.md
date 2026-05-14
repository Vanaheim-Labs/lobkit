# 🦞 LobKit

**LobKit** is a beautiful, native macOS installer for [OpenClaw](https://openclaw.ai) — your personal AI assistant.

No Terminal. No config files. No prior knowledge required. Just click through a few screens and you'll have OpenClaw running and connected to a chat channel in minutes.

---

## What it does

LobKit walks you through:

1. Installing prerequisites (Node.js, Git) — automatically
2. Installing OpenClaw
3. Choosing your AI model provider (Anthropic, OpenAI, etc.) and entering your API key
4. Connecting your first chat channel — **Telegram** (recommended) or Slack
5. Launching OpenClaw and confirming everything works

By the end, you'll be chatting with your AI assistant from your phone.

---

## Status

🚧 **Early development** — not yet ready for public use.

---

## Architecture

- **Native SwiftUI** macOS app (macOS 13+)
- Installer backend driven by `openclaw config patch` + `openclaw gateway install`
- Signed and notarized with Apple Developer ID
- No Electron, no web views — pure native

---

## Building

Requires:
- Xcode 15+
- macOS 13+
- Apple Developer account (for signing)

Open `LobKit.xcodeproj` in Xcode and build.

---

## License

MIT — see [LICENSE](LICENSE)

---

*LobKit is an unofficial community project. OpenClaw is © its respective authors.*
