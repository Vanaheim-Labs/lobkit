import SwiftUI

struct ModelSetupView: View {
    @EnvironmentObject var state: InstallerState
    @State private var showKey = false
    @State private var validationMessage = ""
    @State private var hasValidated = false

    private var providers: [(id: String, name: String, badge: String?, keyURL: String)] {
        [
            ("anthropic", "Anthropic", "Recommended", "https://console.anthropic.com/settings/keys"),
            ("openai", "OpenAI", nil, "https://platform.openai.com/api-keys"),
            ("google", "Google Gemini", nil, "https://aistudio.google.com/apikey"),
            ("other", "Other", nil, ""),
        ]
    }

    private var selectedProvider: (id: String, name: String, badge: String?, keyURL: String) {
        providers.first { $0.id == state.modelProvider } ?? providers[0]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 16) {
                Text("STEP 3 OF 6")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .tracking(1)

                Text("Choose your AI model")
                    .font(.system(size: 26, weight: .bold, design: .rounded))

                Text("Pick a provider and enter your API key. This is how OpenClaw thinks.")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 380, alignment: .leading)

                Spacer().frame(height: 4)

                // Provider picker
                VStack(alignment: .leading, spacing: 8) {
                    Text("Provider")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.secondary)

                    HStack(spacing: 8) {
                        ForEach(providers, id: \.id) { provider in
                            ProviderButton(
                                name: provider.name,
                                badge: provider.badge,
                                isSelected: state.modelProvider == provider.id
                            ) {
                                state.modelProvider = provider.id
                                state.apiKey = ""
                                state.apiKeyValid = false
                                hasValidated = false
                                validationMessage = ""
                            }
                        }
                    }
                }

                // API key field (hidden for "other")
                if state.modelProvider != "other" {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("API Key")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(.secondary)

                            Spacer()

                            if !selectedProvider.keyURL.isEmpty {
                                Button(action: {
                                    if let url = URL(string: selectedProvider.keyURL) {
                                        NSWorkspace.shared.open(url)
                                    }
                                }) {
                                    HStack(spacing: 4) {
                                        Text("Get an API key")
                                            .font(.system(size: 12))
                                        Image(systemName: "arrow.up.forward")
                                            .font(.system(size: 10))
                                    }
                                    .foregroundStyle(.accent)
                                }
                                .buttonStyle(.plain)
                            }
                        }

                        HStack(spacing: 8) {
                            Group {
                                if showKey {
                                    TextField("sk-...", text: $state.apiKey)
                                } else {
                                    SecureField("sk-...", text: $state.apiKey)
                                }
                            }
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 14, design: .monospaced))
                            .onSubmit { validateKey() }
                            .onChange(of: state.apiKey) { _ in
                                // Reset validation when key changes
                                if hasValidated {
                                    hasValidated = false
                                    state.apiKeyValid = false
                                    validationMessage = ""
                                }
                            }

                            Button(action: { showKey.toggle() }) {
                                Image(systemName: showKey ? "eye.slash" : "eye")
                                    .foregroundStyle(.secondary)
                            }
                            .buttonStyle(.plain)

                            Button("Validate") {
                                validateKey()
                            }
                            .buttonStyle(.bordered)
                            .disabled(state.apiKey.isEmpty || state.apiKeyValidating)
                        }

                        // Validation status
                        if state.apiKeyValidating {
                            HStack(spacing: 6) {
                                ProgressView()
                                    .controlSize(.small)
                                Text("Validating...")
                                    .font(.system(size: 13))
                                    .foregroundStyle(.secondary)
                            }
                        } else if hasValidated {
                            HStack(spacing: 6) {
                                if state.apiKeyValid {
                                    Image(systemName: "checkmark.circle.fill")
                                        .foregroundStyle(.green)
                                    Text("Valid API key")
                                        .font(.system(size: 13))
                                        .foregroundStyle(.green)
                                } else {
                                    Image(systemName: "xmark.circle.fill")
                                        .foregroundStyle(.red)
                                    Text(validationMessage.isEmpty ? "Invalid key — check and try again" : validationMessage)
                                        .font(.system(size: 13))
                                        .foregroundStyle(.red)
                                }
                            }
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
                    .background(canContinue ? Color.accentColor : Color.accentColor.opacity(0.4))
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .buttonStyle(.plain)
                .disabled(!canContinue)
            }
            .padding(.horizontal, 48)

            Spacer()
        }
    }

    private var canContinue: Bool {
        if state.modelProvider == "other" { return true }
        return state.apiKeyValid
    }

    private func validateKey() {
        let key = state.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }

        state.apiKeyValidating = true
        hasValidated = false

        Task {
            let valid: Bool
            let message: String

            switch state.modelProvider {
            case "anthropic":
                (valid, message) = await validateAnthropic(key: key)
            case "openai":
                (valid, message) = await validateOpenAI(key: key)
            case "google":
                (valid, message) = await validateGoogle(key: key)
            default:
                valid = true
                message = ""
            }

            await MainActor.run {
                state.apiKeyValid = valid
                state.apiKeyValidating = false
                validationMessage = message
                hasValidated = true
            }
        }
    }

    private func validateAnthropic(key: String) async -> (Bool, String) {
        // POST to messages endpoint with minimal payload — check for non-401
        let result = await InstallService.shared.run(
            "curl -s -o /dev/null -w '%{http_code}' -X POST https://api.anthropic.com/v1/messages " +
            "-H 'x-api-key: \(shellEscape(key))' " +
            "-H 'anthropic-version: 2023-06-01' " +
            "-H 'content-type: application/json' " +
            "-d '{\"model\":\"claude-sonnet-4-5-20250514\",\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'"
        )
        let code = Int(result.output.trimmingCharacters(in: .whitespaces)) ?? 0
        if code == 401 {
            return (false, "Invalid key — check and try again")
        } else if code == 0 {
            return (false, "Could not reach Anthropic API — check your connection")
        }
        return (true, "")
    }

    private func validateOpenAI(key: String) async -> (Bool, String) {
        let result = await InstallService.shared.run(
            "curl -s -o /dev/null -w '%{http_code}' https://api.openai.com/v1/models " +
            "-H 'Authorization: Bearer \(shellEscape(key))'"
        )
        let code = Int(result.output.trimmingCharacters(in: .whitespaces)) ?? 0
        if code == 401 {
            return (false, "Invalid key — check and try again")
        } else if code == 0 {
            return (false, "Could not reach OpenAI API — check your connection")
        }
        return (true, "")
    }

    private func validateGoogle(key: String) async -> (Bool, String) {
        let result = await InstallService.shared.run(
            "curl -s -o /dev/null -w '%{http_code}' 'https://generativelanguage.googleapis.com/v1beta/models?key=\(shellEscape(key))'"
        )
        let code = Int(result.output.trimmingCharacters(in: .whitespaces)) ?? 0
        if code == 401 || code == 403 {
            return (false, "Invalid key — check and try again")
        } else if code == 0 {
            return (false, "Could not reach Google API — check your connection")
        }
        return (true, "")
    }

    /// Basic shell escaping to prevent injection in curl commands
    private func shellEscape(_ s: String) -> String {
        s.replacingOccurrences(of: "'", with: "'\\''")
    }
}

// MARK: - Provider Button

struct ProviderButton: View {
    let name: String
    let badge: String?
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Text(name)
                    .font(.system(size: 13, weight: isSelected ? .semibold : .regular))
                    .lineLimit(1)
                if let badge {
                    Text(badge)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.accent)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(minWidth: 80)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(isSelected ? Color.accentColor.opacity(0.12) : Color.secondary.opacity(0.06))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(isSelected ? Color.accentColor : Color.clear, lineWidth: 1.5)
            )
        }
        .buttonStyle(.plain)
    }
}
