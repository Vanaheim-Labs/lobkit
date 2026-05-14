import SwiftUI

struct FinishingView: View {
    @EnvironmentObject var state: InstallerState
    @State private var hasStarted = false
    @State private var finishError: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 16) {
                Text("STEP 6 OF 6")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .tracking(1)

                Text("Starting OpenClaw")
                    .font(.system(size: 26, weight: .bold, design: .rounded))

                Text("Installing the background service and running a health check.")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 380, alignment: .leading)

                Spacer().frame(height: 8)

                // Task list
                VStack(spacing: 12) {
                    ForEach(state.tasks) { task in
                        FinishingTaskRow(task: task)
                    }
                }
                .padding(20)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color.secondary.opacity(0.06))
                )

                if let error = finishError {
                    Text(error)
                        .font(.system(size: 13))
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: 380, alignment: .leading)
                        .padding(.top, 4)
                }

                if finishError != nil {
                    Spacer().frame(height: 8)
                    Button(action: { runFinishing() }) {
                        HStack {
                            Image(systemName: "arrow.clockwise")
                            Text("Retry")
                                .font(.system(size: 15, weight: .medium))
                        }
                        .padding(.horizontal, 20)
                        .padding(.vertical, 12)
                        .background(Color.secondary.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 48)

            Spacer()
        }
        .onAppear {
            guard !hasStarted else { return }
            hasStarted = true
            runFinishing()
        }
    }

    private func runFinishing() {
        finishError = nil
        state.tasks = [
            TaskResult(label: "Writing configuration...", status: .pending),
            TaskResult(label: "Installing background service...", status: .pending),
            TaskResult(label: "Starting OpenClaw...", status: .pending),
            TaskResult(label: "Health check...", status: .pending),
        ]

        Task {
            // Step 1: Write config
            await setTaskStatus(index: 0, status: .running)
            let configSuccess = await writeConfig()
            if !configSuccess {
                await setTaskStatus(index: 0, status: .failed, detail: "Config write failed")
                await MainActor.run { finishError = "Failed to write configuration. Check that openclaw is installed." }
                return
            }
            await setTaskStatus(index: 0, status: .success)

            // Step 2: Install gateway
            await setTaskStatus(index: 1, status: .running)
            let installResult = await InstallService.shared.run("openclaw gateway install --force")
            if installResult.exitCode != 0 {
                await setTaskStatus(index: 1, status: .failed, detail: installResult.output)
                await MainActor.run { finishError = "Gateway install failed: \(installResult.output)" }
                return
            }
            await setTaskStatus(index: 1, status: .success)

            // Step 3: Restart gateway
            await setTaskStatus(index: 2, status: .running)
            let restartResult = await InstallService.shared.run("openclaw gateway restart")
            if restartResult.exitCode != 0 {
                await setTaskStatus(index: 2, status: .failed, detail: restartResult.output)
                await MainActor.run { finishError = "Gateway restart failed: \(restartResult.output)" }
                return
            }
            await setTaskStatus(index: 2, status: .success)

            // Step 4: Health check
            await setTaskStatus(index: 3, status: .running)
            let doctorResult = await InstallService.shared.run("openclaw doctor --non-interactive")
            if doctorResult.exitCode != 0 {
                await setTaskStatus(index: 3, status: .failed, detail: doctorResult.output)
                await MainActor.run { finishError = "Health check failed: \(doctorResult.output)" }
                return
            }
            await setTaskStatus(index: 3, status: .success)

            // All done — auto-advance after 1.5s
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            await MainActor.run { state.advance() }
        }
    }

    private func writeConfig() async -> Bool {
        let tmpDir = FileManager.default.temporaryDirectory

        // Write model config
        let modelString = modelIdentifier(for: state.modelProvider)
        let apiKey = state.apiKey.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")

        if state.modelProvider != "other" {
            let modelJSON = """
            {
              "agents": { "defaults": { "model": "\(modelString)" } },
              "auth": { "profiles": [{ "id": "\(state.modelProvider)-default", "provider": "\(state.modelProvider)", "apiKey": "\(apiKey)" }] }
            }
            """
            let modelFile = tmpDir.appendingPathComponent("lobkit-model-config.json")
            do {
                try modelJSON.write(to: modelFile, atomically: true, encoding: .utf8)
            } catch {
                return false
            }
            let result = await InstallService.shared.run("openclaw config patch --file '\(modelFile.path)'")
            try? FileManager.default.removeItem(at: modelFile)
            if result.exitCode != 0 { return false }
        }

        // Write channel config
        if state.channelChoice == .telegram && !state.telegramToken.isEmpty {
            let tokenEscaped = state.telegramToken.replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "\"", with: "\\\"")
            let channelJSON = """
            { "channels": { "telegram": { "enabled": true, "token": "\(tokenEscaped)" } } }
            """
            let channelFile = tmpDir.appendingPathComponent("lobkit-channel-config.json")
            do {
                try channelJSON.write(to: channelFile, atomically: true, encoding: .utf8)
            } catch {
                return false
            }
            let result = await InstallService.shared.run("openclaw config patch --file '\(channelFile.path)'")
            try? FileManager.default.removeItem(at: channelFile)
            if result.exitCode != 0 { return false }
        } else if state.channelChoice == .slack && !state.slackBotToken.isEmpty {
            let botEscaped = state.slackBotToken.replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "\"", with: "\\\"")
            let appEscaped = state.slackAppToken.replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "\"", with: "\\\"")
            let channelJSON = """
            { "channels": { "slack": { "enabled": true, "botToken": "\(botEscaped)", "appToken": "\(appEscaped)" } } }
            """
            let channelFile = tmpDir.appendingPathComponent("lobkit-channel-config.json")
            do {
                try channelJSON.write(to: channelFile, atomically: true, encoding: .utf8)
            } catch {
                return false
            }
            let result = await InstallService.shared.run("openclaw config patch --file '\(channelFile.path)'")
            try? FileManager.default.removeItem(at: channelFile)
            if result.exitCode != 0 { return false }
        }

        return true
    }

    private func modelIdentifier(for provider: String) -> String {
        switch provider {
        case "anthropic": return "anthropic/claude-sonnet-4-5"
        case "openai": return "openai/gpt-4o"
        case "google": return "google/gemini-2.0-flash"
        default: return "anthropic/claude-sonnet-4-5"
        }
    }

    @MainActor
    private func setTaskStatus(index: Int, status: TaskStatus, detail: String = "") {
        guard index < state.tasks.count else { return }
        state.tasks[index].status = status
        if !detail.isEmpty {
            state.tasks[index].detail = detail
        }
    }
}

// MARK: - Finishing Task Row

struct FinishingTaskRow: View {
    let task: TaskResult

    var body: some View {
        HStack(spacing: 12) {
            taskIcon
                .frame(width: 22, height: 22)

            Text(task.label)
                .font(.system(size: 14, weight: .medium))

            Spacer()
        }

        if task.status == .failed && !task.detail.isEmpty {
            Text(task.detail)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(.red.opacity(0.8))
                .lineLimit(3)
                .padding(.leading, 34)
        }
    }

    @ViewBuilder
    private var taskIcon: some View {
        switch task.status {
        case .pending:
            Image(systemName: "circle")
                .foregroundStyle(.tertiary)
        case .running:
            ProgressView()
                .controlSize(.small)
        case .success:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case .failed:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(.red)
        case .skipped:
            Image(systemName: "minus.circle.fill")
                .foregroundStyle(.secondary)
        }
    }
}
