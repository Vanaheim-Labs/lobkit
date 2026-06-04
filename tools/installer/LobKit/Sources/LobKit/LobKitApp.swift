import SwiftUI

@main
struct LobKitApp: App {
    @StateObject private var installer = InstallerState()

    var body: some Scene {
        WindowGroup {
            InstallerWizard()
                .environmentObject(installer)
                .frame(width: 720, height: 520)
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
    }
}
