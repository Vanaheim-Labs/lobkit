import SwiftUI

struct ChannelChoiceView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Choose your channel")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("This is where you'll chat with OpenClaw. You can add more later.")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }

                // Telegram — recommended
                ChannelCard(
                    icon: "paperplane.fill",
                    iconColor: .blue,
                    title: "Telegram",
                    badge: "Recommended",
                    badgeColor: .green,
                    description: "The fastest setup — just create a bot and paste a token. One chat window, one assistant. Perfect for personal use.",
                    pros: ["60-second setup", "Works on iPhone & Android", "No extra accounts needed"],
                    isSelected: state.channelChoice == .telegram
                ) {
                    state.channelChoice = .telegram
                }

                // Slack
                ChannelCard(
                    icon: "number.square.fill",
                    iconColor: Color(red: 0.27, green: 0.75, blue: 0.45),
                    title: "Slack",
                    badge: "More powerful",
                    badgeColor: .purple,
                    description: "Connect to a Slack workspace. Supports channels, threads, multiple agents, and team access. Requires creating a Slack app.",
                    pros: ["Team & workspace support", "Slash commands", "Multiple channels"],
                    isSelected: state.channelChoice == .slack
                ) {
                    state.channelChoice = .slack
                }

                Spacer().frame(height: 8)

                HStack {
                    Spacer()
                    Button(action: { state.advance() }) {
                        HStack {
                            Text("Continue with \(state.channelChoice == .telegram ? "Telegram" : "Slack")")
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
            .padding(.horizontal, 48)

            Spacer()
        }
    }
}

struct ChannelCard: View {
    let icon: String
    let iconColor: Color
    let title: String
    let badge: String
    let badgeColor: Color
    let description: String
    let pros: [String]
    let isSelected: Bool
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            HStack(alignment: .top, spacing: 16) {
                Image(systemName: icon)
                    .font(.system(size: 22))
                    .foregroundStyle(iconColor)
                    .frame(width: 36, height: 36)

                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Text(title)
                            .font(.system(size: 16, weight: .semibold))

                        Text(badge)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(badgeColor)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                            .background(badgeColor.opacity(0.12))
                            .clipShape(Capsule())
                    }

                    Text(description)
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    HStack(spacing: 12) {
                        ForEach(pros, id: \.self) { pro in
                            HStack(spacing: 4) {
                                Image(systemName: "checkmark")
                                    .font(.system(size: 10, weight: .bold))
                                    .foregroundStyle(.green)
                                Text(pro)
                                    .font(.system(size: 12))
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                Spacer()

                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 20))
                    .foregroundStyle(isSelected ? Color.accentColor : Color.secondary.opacity(0.4))
            }
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color(NSColor.controlBackgroundColor))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(isSelected ? Color.accentColor : Color.secondary.opacity(0.2), lineWidth: isSelected ? 2 : 1)
                    )
            )
        }
        .buttonStyle(.plain)
    }
}

#Preview {
    InstallerWizard()
        .environmentObject({
            let s = InstallerState()
            s.currentStep = .channelChoice
            return s
        }())
}
