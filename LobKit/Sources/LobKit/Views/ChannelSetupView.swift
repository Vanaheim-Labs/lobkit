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
    @State private var validationMessage = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 16) {
                Text("STEP 5 OF 6")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .tracking(1)

                Text("Connect Telegram")
                    .font(.system(size: 26, weight: .bold, design: .rounded))

                Text("Create a Telegram bot in 60 seconds and paste the token here.")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 420, alignment: .leading)

                Spacer().frame(height: 4)

                // Step-by-step instructions
                VStack(alignment: .leading, spacing: 16) {
                    TelegramStep(number: 1, text: "Open Telegram and search for @BotFather") {
                        // Try native Telegram link first, fall back to web
                        if let tgURL = URL(string: "tg://resolve?domain=BotFather") {
                            NSWorkspace.shared.open(tgURL)
                        } else if let webURL = URL(string: "https://t.me/BotFather") {
                            NSWorkspace.shared.open(webURL)
                        }
                    }

                    TelegramStep(number: 2, text: "Send /newbot and follow the prompts to name your bot", action: nil)

                    TelegramStep(number: 3, text: "BotFather will give you a token that looks like:", action: nil)

                    // Token example
                    Text("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .padding(.leading, 36)
                }
                .padding(20)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color.secondary.opacity(0.06))
                )

                // Token field
                VStack(alignment: .leading, spacing: 8) {
                    Text("Bot Token")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.secondary)

                    HStack(spacing: 8) {
                        TextField("Paste your bot token here", text: $state.telegramToken)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 14, design: .monospaced))
                            .onSubmit { validateToken() }
                            .onChange(of: state.telegramToken) { _ in
                                if state.telegramTokenValid {
                                    state.telegramTokenValid = false
                                    state.telegramBotName = ""
                                    validationMessage = ""
                                }
                            }

                        Button("Validate") {
                            validateToken()
                        }
                        .buttonStyle(.bordered)
                        .disabled(state.telegramToken.isEmpty || state.telegramTokenValidating)
                    }

                    // Validation status
                    if state.telegramTokenValidating {
                        HStack(spacing: 6) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Checking token...")
                                .font(.system(size: 13))
                                .foregroundStyle(.secondary)
                        }
                    } else if state.telegramTokenValid {
                        HStack(spacing: 6) {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                            Text("Connected to @\(state.telegramBotName)")
                                .font(.system(size: 13))
                                .foregroundStyle(.green)
                        }
                    } else if !validationMessage.isEmpty {
                        HStack(spacing: 6) {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.red)
                            Text(validationMessage)
                                .font(.system(size: 13))
                                .foregroundStyle(.red)
                        }
                    }
                }

                Spacer().frame(height: 16)

                Button(action: { state.advance() }) {
                    HStack {
                        Text("Continue")
                            .font(.system(size: 15, weight: .semibold))
                        Image(systemName: "arrow.right")
                    }
                    .padding(.horizontal, 24)
                    .padding(.vertical, 12)
                    .background(state.telegramTokenValid ? Color.accentColor : Color.accentColor.opacity(0.4))
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .buttonStyle(.plain)
                .disabled(!state.telegramTokenValid)
            }
            .padding(.horizontal, 48)

            Spacer()
        }
    }

    private func validateToken() {
        let token = state.telegramToken.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { return }

        state.telegramTokenValidating = true
        validationMessage = ""

        Task {
            let escaped = token.replacingOccurrences(of: "'", with: "'\\''")
            let result = await InstallService.shared.run(
                "curl -s 'https://api.telegram.org/bot\(escaped)/getMe'"
            )

            await MainActor.run {
                state.telegramTokenValidating = false

                if result.exitCode == 0 {
                    // Parse the JSON response to find bot username
                    if let data = result.output.data(using: .utf8),
                       let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let ok = json["ok"] as? Bool, ok,
                       let resultObj = json["result"] as? [String: Any],
                       let username = resultObj["username"] as? String {
                        state.telegramBotName = username
                        state.telegramTokenValid = true
                    } else {
                        validationMessage = "Invalid token — check and try again"
                        state.telegramTokenValid = false
                    }
                } else {
                    validationMessage = "Could not reach Telegram API — check your connection"
                    state.telegramTokenValid = false
                }
            }
        }
    }
}

// MARK: - Telegram Step Row

struct TelegramStep: View {
    let number: Int
    let text: String
    let action: (() -> Void)?

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(number)")
                .font(.system(size: 13, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .frame(width: 24, height: 24)
                .background(Circle().fill(Color.accentColor))

            VStack(alignment: .leading, spacing: 6) {
                Text(text)
                    .font(.system(size: 14))
                    .fixedSize(horizontal: false, vertical: true)

                if let action {
                    Button(action: action) {
                        HStack(spacing: 4) {
                            Text("Open BotFather")
                                .font(.system(size: 12, weight: .medium))
                            Image(systemName: "arrow.up.forward")
                                .font(.system(size: 10))
                        }
                        .foregroundStyle(.accent)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

// MARK: - Slack Setup (placeholder kept for now)

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
