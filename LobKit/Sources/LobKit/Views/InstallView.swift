import SwiftUI

struct InstallView: View {
    @EnvironmentObject var state: InstallerState
    @State private var installing = false
    @State private var succeeded = false
    @State private var failed = false
    @State private var errorMessage: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Step 2 of 6")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                    Text("Installing OpenClaw")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("Downloading and installing OpenClaw on your Mac.")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }

                // Live terminal output
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 6) {
                        Circle().fill(.red.opacity(0.8)).frame(width: 10, height: 10)
                        Circle().fill(.yellow.opacity(0.8)).frame(width: 10, height: 10)
                        Circle().fill(.green.opacity(0.8)).frame(width: 10, height: 10)
                        Spacer()
                        if installing {
                            ProgressView()
                                .scaleEffect(0.5)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color(white: 0.15))

                    ScrollViewReader { proxy in
                        ScrollView {
                            Text(state.service.fullOutput.isEmpty ? "Waiting to start..." : state.service.fullOutput)
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(.green.opacity(0.9))
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(12)
                                .id("terminal-bottom")
                        }
                        .frame(height: 180)
                        .background(Color(white: 0.08))
                        .onChange(of: state.service.fullOutput) { _ in
                            proxy.scrollTo("terminal-bottom", anchor: .bottom)
                        }
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.secondary.opacity(0.2), lineWidth: 1)
                )

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
                }

                HStack {
                    if failed {
                        Button("Retry") {
                            Task { await runInstall() }
                        }
                        .buttonStyle(.bordered)
                    }

                    Spacer()

                    if succeeded {
                        Button(action: { state.advance() }) {
                            HStack {
                                Text("Continue")
                                    .font(.system(size: 15, weight: .semibold))
                                Image(systemName: "arrow.right")
                            }
                            .padding(.horizontal, 24)
                            .padding(.vertical, 12)
                            .background(Color.accentColor)
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
            await runInstall()
        }
    }

    private func runInstall() async {
        installing = true
        failed = false
        succeeded = false
        errorMessage = nil

        let svc = state.service

        // Check if OpenClaw is already installed
        if let ver = await svc.runCapture("openclaw --version") {
            state.openclawVersion = ver
            svc.fullOutput = "OpenClaw already installed: \(ver)\n"

            // Run doctor --fix to migrate any legacy config
            svc.fullOutput += "\nRunning openclaw doctor --fix...\n"
            let doctorResult = try? await svc.run("openclaw doctor --fix --non-interactive")
            if let dr = doctorResult {
                svc.fullOutput += dr.output
            }

            installing = false
            succeeded = true
            return
        }

        // Install OpenClaw
        do {
            let result = try await svc.run("curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard")
            if result.exitCode == 0 {
                if let ver = await svc.runCapture("openclaw --version") {
                    state.openclawVersion = ver
                }
                // Run doctor --fix after fresh install
                svc.fullOutput += "\nRunning openclaw doctor --fix...\n"
                let _ = try? await svc.run("openclaw doctor --fix --non-interactive")
                succeeded = true
            } else {
                failed = true
                errorMessage = "Install failed (exit code \(result.exitCode)). Check the log above."
            }
        } catch {
            failed = true
            errorMessage = "Install failed: \(error.localizedDescription)"
        }

        installing = false
    }
}
