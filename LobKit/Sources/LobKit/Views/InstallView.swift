import SwiftUI

// TODO: Implement OpenClaw install
// This view will:
//  1. Run: curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard
//  2. Show live progress (streaming Process output)
//  3. Handle errors gracefully with retry
//  4. Auto-advance on success

struct InstallView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        PlaceholderStepView(
            title: "Installing OpenClaw",
            subtitle: "Downloading and installing OpenClaw on your Mac.",
            step: "Step 2 of 6"
        ) {
            state.advance()
        }
    }
}
