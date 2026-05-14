import SwiftUI

struct PrerequisitesView: View {
    @EnvironmentObject var state: InstallerState
    @State private var checking = false
    @State private var error: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Step 1 of 6")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                    Text("Checking prerequisites")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("Making sure your Mac has everything OpenClaw needs.")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }

                VStack(alignment: .leading, spacing: 12) {
                    PrereqRow(
                        label: "Homebrew",
                        detail: state.homebrewVersion,
                        checking: checking && state.homebrewVersion == nil
                    )
                    PrereqRow(
                        label: "Node.js (22.16+)",
                        detail: state.nodeVersion,
                        checking: checking && state.nodeVersion == nil && state.homebrewVersion != nil
                    )
                    PrereqRow(
                        label: "Git",
                        detail: state.gitVersion,
                        checking: checking && state.gitVersion == nil && state.nodeVersion != nil
                    )
                }

                if let error {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                        Text(error)
                            .font(.system(size: 13))
                            .foregroundStyle(.secondary)
                    }
                    .padding(12)
                    .background(Color.orange.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }

                if state.prereqsChecked {
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
            await runChecks()
        }
    }

    private func runChecks() async {
        checking = true
        let svc = state.service

        // Homebrew
        if let ver = await svc.runCapture("brew --version | head -1") {
            state.homebrewVersion = ver
        } else {
            error = "Homebrew not found. LobKit will install it during the next step."
            state.homebrewVersion = "Not installed (will be installed)"
        }

        // Node
        if let ver = await svc.runCapture("node --version") {
            state.nodeVersion = ver
            let major = Int(ver.replacingOccurrences(of: "v", with: "").components(separatedBy: ".").first ?? "0") ?? 0
            if major < 22 {
                error = "Node \(ver) is below the minimum (v22.16+). It will be upgraded during install."
            }
        } else {
            state.nodeVersion = "Not installed (will be installed)"
        }

        // Git
        if let ver = await svc.runCapture("git --version") {
            state.gitVersion = ver
        } else {
            state.gitVersion = "Not installed (will be installed)"
        }

        checking = false
        state.prereqsChecked = true
    }
}

struct PrereqRow: View {
    let label: String
    let detail: String?
    let checking: Bool

    var body: some View {
        HStack(spacing: 12) {
            if checking {
                ProgressView()
                    .scaleEffect(0.6)
                    .frame(width: 20, height: 20)
            } else if let detail, !detail.contains("Not installed") {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .frame(width: 20, height: 20)
            } else if detail != nil {
                Image(systemName: "arrow.down.circle")
                    .foregroundStyle(.orange)
                    .frame(width: 20, height: 20)
            } else {
                Image(systemName: "circle")
                    .foregroundStyle(.secondary.opacity(0.3))
                    .frame(width: 20, height: 20)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .font(.system(size: 14, weight: .medium))
                if let detail {
                    Text(detail)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color(NSColor.controlBackgroundColor))
        )
    }
}
