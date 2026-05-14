import SwiftUI

struct InstallerWizard: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        HStack(spacing: 0) {
            // Left sidebar — step progress
            SidebarView()
                .frame(width: 200)

            Divider()

            // Right — active step content
            Group {
                switch state.currentStep {
                case .welcome:       WelcomeView()
                case .prerequisites: PrerequisitesView()
                case .install:       InstallView()
                case .modelSetup:    ModelSetupView()
                case .channelChoice: ChannelChoiceView()
                case .channelSetup:  ChannelSetupView()
                case .finishing:     FinishingView()
                case .done:          DoneView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Color(NSColor.windowBackgroundColor))
    }
}

// MARK: - Sidebar

struct SidebarView: View {
    @EnvironmentObject var state: InstallerState

    private let steps: [(InstallStep, String, String)] = [
        (.welcome,       "hand.wave",         "Welcome"),
        (.prerequisites, "checkmark.shield",  "Prerequisites"),
        (.install,       "arrow.down.circle", "Install"),
        (.modelSetup,    "brain",             "AI Model"),
        (.channelChoice, "bubble.left.and.bubble.right", "Channel"),
        (.channelSetup,  "gear",              "Configure"),
        (.finishing,     "gearshape.2",       "Finishing"),
        (.done,          "party.popper",      "Done"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Logo
            HStack(spacing: 8) {
                Text("🦞")
                    .font(.system(size: 28))
                Text("LobKit")
                    .font(.system(size: 18, weight: .bold, design: .rounded))
            }
            .padding(.horizontal, 20)
            .padding(.top, 28)
            .padding(.bottom, 24)

            // Step list
            ForEach(steps, id: \.0) { (step, icon, label) in
                SidebarStepRow(
                    step: step,
                    icon: icon,
                    label: label,
                    currentStep: state.currentStep
                )
            }

            Spacer()

            Text("For OpenClaw \(Image(systemName: "arrow.up.forward.square"))")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 20)
                .padding(.bottom, 16)
        }
        .background(Color(NSColor.controlBackgroundColor))
    }
}

struct SidebarStepRow: View {
    let step: InstallStep
    let icon: String
    let label: String
    let currentStep: InstallStep

    private var isDone: Bool { currentStep.rawValue > step.rawValue }
    private var isCurrent: Bool { currentStep == step }

    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                Circle()
                    .fill(isDone ? Color.accentColor : isCurrent ? Color.accentColor.opacity(0.15) : Color.secondary.opacity(0.1))
                    .frame(width: 28, height: 28)
                if isDone {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.white)
                } else {
                    Image(systemName: icon)
                        .font(.system(size: 11))
                        .foregroundStyle(isCurrent ? .accent : .secondary)
                }
            }

            Text(label)
                .font(.system(size: 13, weight: isCurrent ? .semibold : .regular))
                .foregroundStyle(isCurrent ? .primary : isDone ? .primary : .secondary)

            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
        .background(isCurrent ? Color.accentColor.opacity(0.07) : Color.clear)
    }
}

// MARK: - Preview

#Preview {
    InstallerWizard()
        .environmentObject(InstallerState())
}
