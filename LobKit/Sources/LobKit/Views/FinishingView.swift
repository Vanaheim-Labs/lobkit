import SwiftUI

// TODO: Implement finishing step
// This view will:
//  1. Run: openclaw gateway install --force
//  2. Run: openclaw gateway restart
//  3. Poll: openclaw gateway status until running
//  4. Run: openclaw doctor --non-interactive
//  5. Show live task list (each item ticks green as it passes)
//  6. Auto-advance to DoneView on full success

struct FinishingView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        PlaceholderStepView(
            title: "Starting OpenClaw",
            subtitle: "Installing the background service and running a health check.",
            step: "Step 6 of 6"
        ) {
            state.advance()
        }
    }
}
