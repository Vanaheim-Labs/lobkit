import SwiftUI

struct ModelSetupView: View {
    @EnvironmentObject var state: InstallerState

    private let providers = [
        ("anthropic", "Anthropic", "Claude Sonnet 4.5", "Recommended"),
        ("openai", "OpenAI", "GPT-4o", nil as String?),
        ("google", "Google", "Gemini 2.5 Pro", nil as String?),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Step 3 of 6")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                    Text("Choose your AI model")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("Pick a provider and enter your API key. This is how OpenClaw thinks.")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }

                // Provider picker
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(providers, id: \.0) { (id, name, model, badge) in
                        ProviderRow(
                            name: name,
                            model: model,
                            badge: badge,
                            isSelected: state.modelProvider == id
                        ) {
                            state.modelProvider = id
                            state.apiKeyValid = false
                            state.apiKeyError = nil
                        }
                    }
                }

                // API key input
                VStack(alignment: .leading, spacing: 8) {
                    Text("API Key")
                        .font(.system(size: 13, weight: .medium))

                    HStack(spacing: 8) {
                        SecureField("Paste your \(state.modelDisplayName) API key", text: $state.apiKey)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 13, design: .monospaced))
                            .onSubmit {
                                Task { await validateKey() }
                            }

                        if state.apiKeyValidating {
                            ProgressView()
                                .scaleEffect(0.7)
                        } else if state.apiKeyValid {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                        }

                        Button("Validate") {
                            Task { await validateKey() }
                        }
                        .buttonStyle(.bordered)
                        .disabled(state.apiKey.isEmpty || state.apiKeyValidating)
                    }

                    if let error = state.apiKeyError {
                        Text(error)
                            .font(.system(size: 12))
                            .foregroundStyle(.red)
                    }

                    Button(action: { openGetKeyURL() }) {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.up.right.square")
                            Text("Get a \(state.modelDisplayName) API key")
                        }
                        .font(.system(size: 12))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.accent)
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
                        .background(state.apiKeyValid ? Color.accentColor : Color.secondary.opacity(0.3))
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                    .disabled(!state.apiKeyValid)
                }
            }
            .padding(.horizontal, 48)

            Spacer()
        }
    }

    private func validateKey() async {
        state.apiKeyValidating = true
        state.apiKeyError = nil
        state.apiKeyValid = false

        let svc = state.service
        let key = shellEscape(state.apiKey)

        switch state.modelProvider {
        case "anthropic":
            let cmd = """
            curl -s -o /dev/null -w '%{http_code}' \
              -H 'x-api-key: \(key)' \
              -H 'anthropic-version: 2023-06-01' \
              -H 'content-type: application/json' \
              -d '{"model":"claude-sonnet-4-5-20250514","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}' \
              https://api.anthropic.com/v1/messages
            """
            if let result = await svc.runCapture(cmd) {
                if result == "200" {
                    state.apiKeyValid = true
                } else if result == "401" {
                    state.apiKeyError = "Invalid API key. Check it and try again."
                } else {
                    state.apiKeyError = "Unexpected response (\(result)). The key may still work."
                    state.apiKeyValid = true
                }
            } else {
                state.apiKeyError = "Could not reach the API. Check your network."
            }

        case "openai":
            let cmd = """
            curl -s -o /dev/null -w '%{http_code}' \
              -H 'Authorization: Bearer \(key)' \
              https://api.openai.com/v1/models
            """
            if let result = await svc.runCapture(cmd) {
                state.apiKeyValid = result == "200"
                if !state.apiKeyValid { state.apiKeyError = "Invalid API key (HTTP \(result))." }
            } else {
                state.apiKeyError = "Could not reach the API."
            }

        case "google":
            let cmd = """
            curl -s -o /dev/null -w '%{http_code}' \
              'https://generativelanguage.googleapis.com/v1beta/models?key=\(key)'
            """
            if let result = await svc.runCapture(cmd) {
                state.apiKeyValid = result == "200"
                if !state.apiKeyValid { state.apiKeyError = "Invalid API key (HTTP \(result))." }
            } else {
                state.apiKeyError = "Could not reach the API."
            }

        default:
            state.apiKeyValid = true
        }

        state.apiKeyValidating = false
    }

    private func openGetKeyURL() {
        let url: String
        switch state.modelProvider {
        case "anthropic": url = "https://console.anthropic.com/settings/keys"
        case "openai": url = "https://platform.openai.com/api-keys"
        case "google": url = "https://aistudio.google.com/apikey"
        default: return
        }
        if let u = URL(string: url) { NSWorkspace.shared.open(u) }
    }

    private func shellEscape(_ s: String) -> String {
        s.replacingOccurrences(of: "'", with: "'\\''")
    }
}

struct ProviderRow: View {
    let name: String
    let model: String
    let badge: String?
    let isSelected: Bool
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            HStack(spacing: 12) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isSelected ? Color.accentColor : .secondary.opacity(0.4))
                    .font(.system(size: 18))

                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text(name)
                            .font(.system(size: 14, weight: .medium))
                        if let badge {
                            Text(badge)
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(.green)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 1)
                                .background(Color.green.opacity(0.12))
                                .clipShape(Capsule())
                        }
                    }
                    Text(model)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }

                Spacer()
            }
            .padding(10)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(isSelected ? Color.accentColor.opacity(0.06) : Color(NSColor.controlBackgroundColor))
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(isSelected ? Color.accentColor.opacity(0.4) : Color.secondary.opacity(0.15), lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
    }
}
