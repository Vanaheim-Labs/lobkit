import SwiftUI

struct WelcomeView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 16) {
                Text("🦞")
                    .font(.system(size: 56))

                Text("Set up OpenClaw\nin minutes.")
                    .font(.system(size: 32, weight: .bold, design: .rounded))
                    .lineSpacing(4)

                Text("LobKit will install OpenClaw, connect your AI model, and set up your first chat channel — no Terminal required.")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 380)

                Spacer().frame(height: 8)

                VStack(alignment: .leading, spacing: 10) {
                    BulletRow(icon: "clock", text: "Takes about 5 minutes")
                    BulletRow(icon: "lock.shield", text: "Everything runs locally on your Mac")
                    BulletRow(icon: "bubble.left", text: "Chat with your AI from your phone")
                }

                Spacer().frame(height: 24)

                Button(action: { state.advance() }) {
                    HStack {
                        Text("Get Started")
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
            .padding(.horizontal, 48)

            Spacer()
        }
    }
}

struct BulletRow: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 13))
                .foregroundStyle(Color.accentColor)
                .frame(width: 18)
            Text(text)
                .font(.system(size: 14))
                .foregroundStyle(.secondary)
        }
    }
}

#Preview {
    InstallerWizard()
        .environmentObject(InstallerState())
}
