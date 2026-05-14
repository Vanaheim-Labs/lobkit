import SwiftUI

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

// MARK: - Telegram Setup

struct TelegramSetupView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Step 5 of 6")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                    Text("Connect Telegram")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("Create a Telegram bot in 60 seconds and paste the token here.")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }

                // Step-by-step guide
                VStack(alignment: .leading, spacing: 12) {
                    InstructionRow(number: 1, text: "Open Telegram and search for @BotFather")
                    InstructionRow(number: 2, text: "Send /newbot and follow the prompts to name your bot")
                    InstructionRow(number: 3, text: "BotFather will give you a token — copy it")
                    InstructionRow(number: 4, text: "Paste the token below")

                    Button(action: {
                        if let url = URL(string: "https://t.me/BotFather") {
                            NSWorkspace.shared.open(url)
                        }
                    }) {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.up.right.square")
                            Text("Open BotFather in Telegram")
                        }
                        .font(.system(size: 13))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.accent)
                }

                // Token input
                VStack(alignment: .leading, spacing: 8) {
                    Text("Bot Token")
                        .font(.system(size: 13, weight: .medium))

                    HStack(spacing: 8) {
                        SecureField("Paste your bot token", text: $state.telegramToken)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 13, design: .monospaced))
                            .onSubmit {
                                Task { await validateTelegramToken() }
                            }

                        if state.telegramValidating {
                            ProgressView()
                                .scaleEffect(0.7)
                        } else if state.telegramTokenValid {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                        }

                        Button("Validate") {
                            Task { await validateTelegramToken() }
                        }
                        .buttonStyle(.bordered)
                        .disabled(state.telegramToken.isEmpty || state.telegramValidating)
                    }

                    if state.telegramTokenValid, !state.telegramBotName.isEmpty {
                        HStack(spacing: 6) {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                            Text("Connected as @\(state.telegramBotName)")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(.green)
                        }
                    }

                    if let error = state.telegramError {
                        Text(error)
                            .font(.system(size: 12))
                            .foregroundStyle(.red)
                    }
                }

                HStack {
                    Spacer()
                    Button(action: { state.advance() }) {
                        HStack {
                            Text("Continue")
                                .font(.system(size: 15, weight: .semibold))
                            Image(systemName: "arrow.right")
                        }
                        .padding(.horizontal, 24)
                        .padding(.vertical, 12)
                        .background(state.telegramTokenValid ? Color.accentColor : Color.secondary.opacity(0.3))
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                    .disabled(!state.telegramTokenValid)
                }
            }
            .padding(.horizontal, 48)

            Spacer()
        }
    }

    private func validateTelegramToken() async {
        state.telegramValidating = true
        state.telegramError = nil
        state.telegramTokenValid = false
        state.telegramBotName = ""

        let token = state.telegramToken.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "'", with: "'\\''")
        let svc = state.service

        let cmd = "curl -s 'https://api.telegram.org/bot\(token)/getMe'"
        if let result = await svc.runCapture(cmd) {
            if let data = result.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let ok = json["ok"] as? Bool, ok,
               let resultObj = json["result"] as? [String: Any],
               let username = resultObj["username"] as? String {
                state.telegramBotName = username
                state.telegramTokenValid = true
            } else if result.contains("\"ok\":false") {
                state.telegramError = "Invalid token. Make sure you copied the full token from BotFather."
            } else {
                state.telegramError = "Could not verify the token. Check your internet connection."
            }
        } else {
            state.telegramError = "Could not reach Telegram. Check your internet connection."
        }

        state.telegramValidating = false
    }
}

struct InstructionRow: View {
    let number: Int
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text("\(number)")
                .font(.system(size: 12, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .frame(width: 22, height: 22)
                .background(Color.accentColor)
                .clipShape(Circle())

            Text(text)
                .font(.system(size: 13))
                .foregroundStyle(.primary)
        }
    }
}

// MARK: - Slack Setup

struct SlackSetupView: View {
    @EnvironmentObject var state: InstallerState
    @State private var manifestCopied = false

    private let slackManifest = """
    {
      "display_information": { "name": "OpenClaw" },
      "features": {
        "bot_user": { "display_name": "OpenClaw", "always_online": true }
      },
      "oauth_config": {
        "scopes": {
          "bot": ["app_mentions:read", "channels:history", "channels:read", "chat:write", "groups:history", "groups:read", "im:history", "im:read", "im:write", "mpim:history", "mpim:read", "reactions:read", "reactions:write", "users:read", "files:read", "files:write"]
        }
      },
      "settings": {
        "event_subscriptions": {
          "bot_events": ["app_mention", "message.channels", "message.groups", "message.im", "message.mpim"]
        },
        "interactivity": { "is_enabled": false },
        "org_deploy_enabled": false,
        "socket_mode_enabled": true
      }
    }
    """

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Step 5 of 6")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                    Text("Connect Slack")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("Create a Slack app and paste your tokens below.")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }

                // Manifest section
                VStack(alignment: .leading, spacing: 8) {
                    Text("1. Copy this app manifest:")
                        .font(.system(size: 13, weight: .medium))

                    VStack(alignment: .leading, spacing: 0) {
                        HStack {
                            Spacer()
                            Button(action: {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(slackManifest, forType: .string)
                                manifestCopied = true
                            }) {
                                HStack(spacing: 4) {
                                    Image(systemName: manifestCopied ? "checkmark" : "doc.on.doc")
                                    Text(manifestCopied ? "Copied" : "Copy")
                                }
                                .font(.system(size: 11))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(Color.secondary.opacity(0.1))
                                .clipShape(Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                        .padding(.horizontal, 8)
                        .padding(.top, 6)

                        Text(slackManifest)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .padding(8)
                    }
                    .background(Color(NSColor.controlBackgroundColor))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("2. Create the Slack app:")
                        .font(.system(size: 13, weight: .medium))

                    Button(action: {
                        if let url = URL(string: "https://api.slack.com/apps?new_app=1&manifest_json=") {
                            NSWorkspace.shared.open(url)
                        }
                    }) {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.up.right.square")
                            Text("Open Slack App Creator")
                        }
                        .font(.system(size: 13))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.accent)

                    Text("Paste the manifest, then go to OAuth & Permissions to install and get tokens.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }

                // Token inputs
                VStack(alignment: .leading, spacing: 12) {
                    Text("3. Paste your tokens:")
                        .font(.system(size: 13, weight: .medium))

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Bot Token (xoxb-...)")
                            .font(.system(size: 12, weight: .medium))
                        SecureField("xoxb-...", text: $state.slackBotToken)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 13, design: .monospaced))
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("App-Level Token (xapp-...)")
                            .font(.system(size: 12, weight: .medium))
                        SecureField("xapp-...", text: $state.slackAppToken)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 13, design: .monospaced))
                        Text("Generate under Basic Information > App-Level Tokens with connections:write scope.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                }

                HStack {
                    Spacer()
                    Button(action: { state.advance() }) {
                        HStack {
                            Text("Continue")
                                .font(.system(size: 15, weight: .semibold))
                            Image(systemName: "arrow.right")
                        }
                        .padding(.horizontal, 24)
                        .padding(.vertical, 12)
                        .background(slackTokensValid ? Color.accentColor : Color.secondary.opacity(0.3))
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                    .disabled(!slackTokensValid)
                }
            }
            .padding(.horizontal, 48)
            .padding(.vertical, 32)
        }
    }

    private var slackTokensValid: Bool {
        state.slackBotToken.hasPrefix("xoxb-") && state.slackAppToken.hasPrefix("xapp-")
    }
}
