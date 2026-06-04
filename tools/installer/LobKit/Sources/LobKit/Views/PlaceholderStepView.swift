import SwiftUI

/// Temporary placeholder used while building out individual step views
struct PlaceholderStepView: View {
    let title: String
    let subtitle: String
    let step: String
    let onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            VStack(alignment: .leading, spacing: 16) {
                Text(step)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                    .tracking(1)

                Text(title)
                    .font(.system(size: 26, weight: .bold, design: .rounded))

                Text(subtitle)
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 380)

                Spacer().frame(height: 16)

                // Placeholder content
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.secondary.opacity(0.08))
                    .frame(maxWidth: .infinity)
                    .frame(height: 120)
                    .overlay(
                        Text("Coming soon")
                            .font(.system(size: 13))
                            .foregroundStyle(.tertiary)
                    )

                Spacer().frame(height: 16)

                Button(action: onContinue) {
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
            .padding(.horizontal, 48)

            Spacer()
        }
    }
}
