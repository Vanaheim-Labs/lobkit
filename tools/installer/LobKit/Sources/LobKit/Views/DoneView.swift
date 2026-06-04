import SwiftUI

struct DoneView: View {
    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            VStack(spacing: 20) {
                Text("🎉")
                    .font(.system(size: 64))

                Text("OpenClaw is running!")
                    .font(.system(size: 28, weight: .bold, design: .rounded))

                Text("Your AI assistant is set up and ready.\nSend it a message to get started.")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)

                Spacer().frame(height: 8)

                HStack(spacing: 12) {
                    Button("Open Dashboard") {
                        let task = Process()
                        task.launchPath = "/usr/bin/env"
                        task.arguments = ["openclaw", "dashboard"]
                        try? task.run()
                    }
                    .buttonStyle(.borderedProminent)

                    Button("Quit LobKit") {
                        NSApplication.shared.terminate(nil)
                    }
                    .buttonStyle(.bordered)
                }
            }
            .padding(.horizontal, 48)

            Spacer()
        }
    }
}

#Preview {
    InstallerWizard()
        .environmentObject({
            let s = InstallerState()
            s.currentStep = .done
            return s
        }())
}
