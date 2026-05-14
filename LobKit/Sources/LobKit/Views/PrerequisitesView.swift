import SwiftUI

// TODO: Implement prerequisites check + auto-install
// This view will:
//  1. Check for Node 22.16+ (show version, offer upgrade if old)
//  2. Check for Git (usually present on macOS via Xcode CLT)
//  3. Show live status rows as checks run
//  4. Auto-advance when all pass, or show error with remediation

struct PrerequisitesView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        PlaceholderStepView(
            title: "Checking prerequisites",
            subtitle: "We'll make sure your Mac has everything OpenClaw needs.",
            step: "Step 1 of 6"
        ) {
            state.advance()
        }
    }
}
