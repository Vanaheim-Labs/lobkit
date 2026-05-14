import SwiftUI

// TODO: Implement model provider selection + API key entry
// This view will:
//  1. Show provider options: Anthropic (recommended), OpenAI, Google, Other
//  2. Show API key text field with inline validation (test the key via a dummy API call)
//  3. Link to "Get an API key" for each provider
//  4. Run: openclaw config patch with the chosen provider + key
//  5. Advance on success

struct ModelSetupView: View {
    @EnvironmentObject var state: InstallerState

    var body: some View {
        PlaceholderStepView(
            title: "Choose your AI model",
            subtitle: "Pick a provider and enter your API key. This is how OpenClaw thinks.",
            step: "Step 3 of 6"
        ) {
            state.advance()
        }
    }
}
