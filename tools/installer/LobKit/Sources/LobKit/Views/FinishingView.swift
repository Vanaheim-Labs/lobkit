import SwiftUI

struct FinishingView: View {
    @EnvironmentObject var state: InstallerState
    @State private var running = false
    @State private var allDone = false
    @State private var errorMessage: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Step 6 of 6")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                    Text("Starting OpenClaw")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("Configuring your settings and launching the background service.")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }

                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(state.tasks.enumerated()), id: \.element.id) { _, task in
                        FinishingTaskRow(task: task)
                    }
                }

                if let errorMessage {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                        Text(errorMessage)
                            .font(.system(size: 13))
                    }
                    .padding(12)
                    .background(Color.red.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 8))

                    Button("Retry") {
                        Task { await runFinishing() }
                    }
                    .buttonStyle(.bordered)
                }

                if allDone {
                    HStack {
                        Spacer()
                        Button(action: { state.advance() }) {
                            HStack {
                                Text("Finish")
                                    .font(.system(size: 15, weight: .semibold))
                                Image(systemName: "checkmark")
                            }
                            .padding(.horizontal, 24)
                            .padding(.vertical, 12)
                            .background(Color.green)
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .padding(.horizontal, 48)

            Spacer()
        }
        .task {
            await runFinishing()
        }
    }

    private func runFinishing() async {
        running = true
        allDone = false
        errorMessage = nil

        state.tasks = [
            TaskResult(label: "Configure model provider", status: .pending),
            TaskResult(label: "Configure messaging channel", status: .pending),
            TaskResult(label: "Install gateway daemon", status: .pending),
            TaskResult(label: "Health check", status: .pending),
        ]

        let svc = state.service

        // 1. Configure model provider
        state.tasks[0].status = .running
        let apiKey = state.apiKey.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let modelJSON = """
        {"agents":{"defaults":{"model":"\(state.modelId)"}},"auth":{"profiles":[{"id":"\(state.modelProvider)-default","provider":"\(state.modelProvider)","apiKey":"\(apiKey)"}]}}
        """
        let modelFile = FileManager.default.temporaryDirectory.appendingPathComponent("lobkit-model-config.json")
        do {
            try modelJSON.write(to: modelFile, atomically: true, encoding: .utf8)
            if await svc.runOk("openclaw config patch --file '\(modelFile.path)'") {
                state.tasks[0].status = .success
                state.tasks[0].detail = state.modelDisplayName
            } else {
                state.tasks[0].status = .failed
                state.tasks[0].detail = "Failed to patch model config"
                errorMessage = "Could not configure the model provider."
                running = false
                return
            }
            try? FileManager.default.removeItem(at: modelFile)
        } catch {
            state.tasks[0].status = .failed
            errorMessage = "Could not write config file."
            running = false
            return
        }

        // 2. Configure channel
        state.tasks[1].status = .running
        var channelOk = false

        switch state.channelChoice {
        case .telegram:
            let tokenEscaped = state.telegramToken.replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "\"", with: "\\\"")
            let channelJSON = """
            {"channels":{"telegram":{"enabled":true,"token":"\(tokenEscaped)"}}}
            """
            let channelFile = FileManager.default.temporaryDirectory.appendingPathComponent("lobkit-channel-config.json")
            do {
                try channelJSON.write(to: channelFile, atomically: true, encoding: .utf8)
                channelOk = await svc.runOk("openclaw config patch --file '\(channelFile.path)'")
                try? FileManager.default.removeItem(at: channelFile)
            } catch {
                channelOk = false
            }
            if channelOk {
                state.tasks[1].detail = "Telegram (@\(state.telegramBotName))"
            }

        case .slack:
            let botEscaped = state.slackBotToken.replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "\"", with: "\\\"")
            let appEscaped = state.slackAppToken.replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "\"", with: "\\\"")
            let channelJSON = """
            {"channels":{"slack":{"enabled":true,"botToken":"\(botEscaped)","appToken":"\(appEscaped)"}}}
            """
            let channelFile = FileManager.default.temporaryDirectory.appendingPathComponent("lobkit-channel-config.json")
            do {
                try channelJSON.write(to: channelFile, atomically: true, encoding: .utf8)
                channelOk = await svc.runOk("openclaw config patch --file '\(channelFile.path)'")
                try? FileManager.default.removeItem(at: channelFile)
            } catch {
                channelOk = false
            }
            if channelOk {
                state.tasks[1].detail = "Slack"
            }

        case .skip:
            channelOk = true
            state.tasks[1].status = .skipped
            state.tasks[1].detail = "Skipped"
        }

        if state.channelChoice != .skip {
            state.tasks[1].status = channelOk ? .success : .failed
            if !channelOk {
                errorMessage = "Could not configure the messaging channel."
                running = false
                return
            }
        }

        // 3. Install gateway daemon
        state.tasks[2].status = .running
        let gatewayOk = await svc.runOk("openclaw gateway install --force && sleep 1 && openclaw gateway restart")
        state.tasks[2].status = gatewayOk ? .success : .failed
        if !gatewayOk {
            state.tasks[2].detail = "Failed — check openclaw doctor"
            errorMessage = "Gateway install failed. Try running 'openclaw doctor --fix' in Terminal."
            running = false
            return
        }
        state.tasks[2].detail = "LaunchAgent installed"

        // 4. Health check
        state.tasks[3].status = .running
        try? await Task.sleep(nanoseconds: 3_000_000_000)

        if let status = await svc.runCapture("openclaw gateway status") {
            if status.contains("running") || status.contains("listening") || status.contains("18789") {
                state.tasks[3].status = .success
                state.tasks[3].detail = "Gateway is running"
            } else {
                state.tasks[3].status = .failed
                state.tasks[3].detail = status
                errorMessage = "Gateway doesn't appear to be running."
                running = false
                return
            }
        } else {
            state.tasks[3].status = .failed
            state.tasks[3].detail = "Could not check status"
        }

        running = false
        allDone = state.tasks.allSatisfy { $0.status == .success || $0.status == .skipped }
    }
}

struct FinishingTaskRow: View {
    let task: TaskResult

    var body: some View {
        HStack(spacing: 12) {
            Group {
                switch task.status {
                case .pending:
                    Image(systemName: "circle")
                        .foregroundStyle(.secondary.opacity(0.3))
                case .running:
                    ProgressView()
                        .scaleEffect(0.6)
                case .success:
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                case .failed:
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.red)
                case .skipped:
                    Image(systemName: "minus.circle")
                        .foregroundStyle(.secondary)
                }
            }
            .frame(width: 20)

            VStack(alignment: .leading, spacing: 2) {
                Text(task.label)
                    .font(.system(size: 14, weight: .medium))
                if !task.detail.isEmpty {
                    Text(task.detail)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color(NSColor.controlBackgroundColor))
        )
    }
}
