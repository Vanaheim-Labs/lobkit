import Foundation
import Combine

/// The overall install step sequence
enum InstallStep: Int, CaseIterable {
    case welcome        = 0
    case prerequisites  = 1
    case install        = 2
    case modelSetup     = 3
    case channelChoice  = 4
    case channelSetup   = 5
    case finishing      = 6
    case done           = 7
}

/// Which messaging channel the user chose
enum ChannelChoice {
    case telegram
    case slack
    case skip
}

/// Represents the result of a single install task
struct TaskResult: Identifiable {
    let id = UUID()
    let label: String
    var status: TaskStatus
    var detail: String = ""
}

enum TaskStatus {
    case pending
    case running
    case success
    case failed
    case skipped
}

@MainActor
class InstallerState: ObservableObject {
    @Published var currentStep: InstallStep = .welcome
    @Published var channelChoice: ChannelChoice = .telegram

    // Model config
    @Published var modelProvider: String = "anthropic"
    @Published var apiKey: String = ""
    @Published var apiKeyValid: Bool = false
    @Published var apiKeyValidating: Bool = false

    // Telegram config
    @Published var telegramToken: String = ""
    @Published var telegramBotName: String = ""

    // Slack config
    @Published var slackBotToken: String = ""
    @Published var slackAppToken: String = ""

    // Prerequisites
    @Published var prereqNodeStatus: TaskStatus = .pending
    @Published var prereqNodeDetail: String = ""
    @Published var prereqGitStatus: TaskStatus = .pending
    @Published var prereqGitDetail: String = ""
    @Published var prereqOpenClawStatus: TaskStatus = .pending
    @Published var prereqOpenClawDetail: String = ""

    // Telegram validation
    @Published var telegramTokenValid: Bool = false
    @Published var telegramTokenValidating: Bool = false

    // Install progress
    @Published var tasks: [TaskResult] = []
    @Published var isInstalling: Bool = false
    @Published var installError: String? = nil

    var prereqsAllPassed: Bool {
        prereqNodeStatus == .success && prereqGitStatus == .success && prereqOpenClawStatus == .success
    }

    func resetPrereqs() {
        prereqNodeStatus = .pending
        prereqNodeDetail = ""
        prereqGitStatus = .pending
        prereqGitDetail = ""
        prereqOpenClawStatus = .pending
        prereqOpenClawDetail = ""
    }

    func advance() {
        guard let next = InstallStep(rawValue: currentStep.rawValue + 1) else { return }
        currentStep = next
    }

    func goTo(_ step: InstallStep) {
        currentStep = step
    }
}
