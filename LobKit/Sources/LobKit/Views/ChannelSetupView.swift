import SwiftUI

// TODO: Implement channel-specific setup
// Telegram path:
//  1. Show step-by-step: open Telegram → find BotFather → /newbot → copy token
//  2. Paste token field + validate (hit Telegram API to confirm token is valid)
//  3. Run: openclaw config patch with telegram token
//  4. Advance on success
//
// Slack path:
//  1. Show manifest JSON with copy button
//  2. "Open Slack App Creator" button → opens api.slack.com/apps/new in browser
//  3. Step-by-step visual guide (paste manifest, generate tokens)
//  4. Two token fields: App Token (xapp-...) + Bot Token (xoxb-...)
//  5. Validate both tokens
//  6. Run: openclaw config patch with slack tokens
//  7. Advance on success

struct ChannelSetupView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        if state.channelChoice == .telegram {
            TelegramSetupView()
        } else {
            SlackSetupView()
        }
    }
}

struct TelegramSetupView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        PlaceholderStepView(
            title: "Connect Telegram",
            subtitle: "Create a Telegram bot in 60 seconds and paste the token here.",
            step: "Step 5 of 6"
        ) {
            state.advance()
        }
    }
}

struct SlackSetupView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        PlaceholderStepView(
            title: "Connect Slack",
            subtitle: "Create a Slack app and paste your tokens. We'll guide you through it.",
            step: "Step 5 of 6"
        ) {
            state.advance()
        }
    }
}
