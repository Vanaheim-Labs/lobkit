import SwiftUI

struct PrerequisitesView: View {
    @EnvironmentObject var state: InstallerState
    @State private var hasStarted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 16) {
                Text("STEP 1 OF 6")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .tracking(1)

                Text("Checking prerequisites")
                    .font(.system(size: 26, weight: .bold, design: .rounded))

                Text("We'll make sure your Mac has everything OpenClaw needs.")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 380, alignment: .leading)

                Spacer().frame(height: 8)

                VStack(spacing: 12) {
                    PrereqRow(label: "Node.js", detail: state.prereqNodeDetail, status: state.prereqNodeStatus)
                    PrereqRow(label: "Git", detail: state.prereqGitDetail, status: state.prereqGitStatus)
                    PrereqRow(label: "OpenClaw", detail: state.prereqOpenClawDetail, status: state.prereqOpenClawStatus)
                }
                .padding(20)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color.secondary.opacity(0.06))
                )

                if let errorText = errorMessage {
                    Text(errorText)
                        .font(.system(size: 13))
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: 380, alignment: .leading)
                        .padding(.top, 4)
                }

                Spacer().frame(height: 16)

                HStack(spacing: 12) {
                    if state.prereqsAllPassed {
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

                    if hasAnyFailure {
                        Button(action: { runChecks() }) {
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
            }
            .padding(.horizontal, 48)

            Spacer()
        }
        .onAppear {
            guard !hasStarted else { return }
            hasStarted = true
            runChecks()
        }
    }

    private var hasAnyFailure: Bool {
        [state.prereqNodeStatus, state.prereqGitStatus, state.prereqOpenClawStatus].contains(.failed)
    }

    private var errorMessage: String? {
        if state.prereqNodeStatus == .failed {
            return "Node.js 22.16+ is required. Install it from nodejs.org or via nvm."
        }
        if state.prereqGitStatus == .failed {
            return "Git is required. Install Xcode Command Line Tools: xcode-select --install"
        }
        if state.prereqOpenClawStatus == .failed {
            return "OpenClaw installation failed. Check your internet connection and try again."
        }
        return nil
    }

    private func runChecks() {
        state.resetPrereqs()
        Task {
            await checkNode()
            await checkGit()
            await checkOpenClaw()
        }
    }

    private func checkNode() async {
        await MainActor.run { state.prereqNodeStatus = .running }
        let result = await InstallService.shared.run("node --version")
        await MainActor.run {
            if result.exitCode == 0 {
                let version = result.output.trimmingCharacters(in: CharacterSet(charactersIn: "v"))
                state.prereqNodeDetail = "v\(version)"
                // Check version >= 22.16
                let parts = version.split(separator: ".").compactMap { Int($0) }
                if parts.count >= 2, (parts[0] > 22 || (parts[0] == 22 && parts[1] >= 16)) {
                    state.prereqNodeStatus = .success
                } else {
                    state.prereqNodeDetail = "v\(version) (need 22.16+)"
                    state.prereqNodeStatus = .failed
                }
            } else {
                state.prereqNodeDetail = "Not found"
                state.prereqNodeStatus = .failed
            }
        }
    }

    private func checkGit() async {
        await MainActor.run { state.prereqGitStatus = .running }
        let result = await InstallService.shared.run("git --version")
        await MainActor.run {
            if result.exitCode == 0 {
                // e.g. "git version 2.39.3 (Apple Git-146)"
                let ver = result.output.replacingOccurrences(of: "git version ", with: "")
                state.prereqGitDetail = ver
                state.prereqGitStatus = .success
            } else {
                state.prereqGitDetail = "Not found"
                state.prereqGitStatus = .failed
            }
        }
    }

    private func checkOpenClaw() async {
        await MainActor.run { state.prereqOpenClawStatus = .running }
        let result = await InstallService.shared.run("openclaw --version")

        if result.exitCode == 0 {
            // OpenClaw exists — check for stale config with doctor
            await MainActor.run {
                state.prereqOpenClawDetail = result.output
            }
            let doctorResult = await InstallService.shared.run("openclaw doctor --non-interactive")
            if doctorResult.exitCode != 0 {
                // Stale config detected — run fix
                await MainActor.run {
                    state.prereqOpenClawDetail = "Fixing config..."
                }
                let fixResult = await InstallService.shared.run("openclaw doctor --fix")
                await MainActor.run {
                    if fixResult.exitCode == 0 {
                        state.prereqOpenClawDetail = result.output + " (repaired)"
                        state.prereqOpenClawStatus = .success
                    } else {
                        state.prereqOpenClawDetail = "Doctor fix failed"
                        state.prereqOpenClawStatus = .failed
                    }
                }
            } else {
                await MainActor.run {
                    state.prereqOpenClawStatus = .success
                }
            }
        } else {
            // Not installed — run installer
            await MainActor.run {
                state.prereqOpenClawDetail = "Installing..."
            }
            let installResult = await InstallService.shared.run("curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard")
            if installResult.exitCode == 0 {
                // Verify it's now available
                let verifyResult = await InstallService.shared.run("openclaw --version")
                await MainActor.run {
                    if verifyResult.exitCode == 0 {
                        state.prereqOpenClawDetail = verifyResult.output
                        state.prereqOpenClawStatus = .success
                    } else {
                        state.prereqOpenClawDetail = "Installed but not found in PATH"
                        state.prereqOpenClawStatus = .failed
                    }
                }
            } else {
                await MainActor.run {
                    state.prereqOpenClawDetail = "Install failed"
                    state.prereqOpenClawStatus = .failed
                }
            }
        }
    }
}

// MARK: - Prerequisite Row

struct PrereqRow: View {
    let label: String
    let detail: String
    let status: TaskStatus

    var body: some View {
        HStack(spacing: 12) {
            statusIcon
                .frame(width: 22, height: 22)

            Text(label)
                .font(.system(size: 14, weight: .medium))

            Spacer()

            if !detail.isEmpty {
                Text(detail)
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch status {
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
