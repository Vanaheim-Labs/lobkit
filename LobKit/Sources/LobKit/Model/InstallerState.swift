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
    @Published var apiKeyError: String? = nil

    // Telegram config
    @Published var telegramToken: String = ""
    @Published var telegramBotName: String = ""
    @Published var telegramTokenValid: Bool = false
    @Published var telegramValidating: Bool = false
    @Published var telegramError: String? = nil

    // Slack config
    @Published var slackBotToken: String = ""
    @Published var slackAppToken: String = ""
    @Published var slackBotTokenValid: Bool = false

    // Prerequisites
    @Published var homebrewVersion: String? = nil
    @Published var nodeVersion: String? = nil
    @Published var gitVersion: String? = nil
    @Published var openclawVersion: String? = nil
    @Published var prereqsChecked: Bool = false

    // Install progress
    @Published var tasks: [TaskResult] = []
    @Published var isInstalling: Bool = false
    @Published var installError: String? = nil
    @Published var installLog: String = ""

    let service = InstallService()

    func advance() {
        guard let next = InstallStep(rawValue: currentStep.rawValue + 1) else { return }
        currentStep = next
    }

    func goTo(_ step: InstallStep) {
        currentStep = step
    }

    var modelDisplayName: String {
        switch modelProvider {
        case "anthropic": return "Anthropic (Claude)"
        case "openai": return "OpenAI (GPT)"
        case "google": return "Google (Gemini)"
        default: return modelProvider
        }
    }

    var modelId: String {
        switch modelProvider {
        case "anthropic": return "anthropic/claude-sonnet-4-5"
        case "openai": return "openai/gpt-4o"
        case "google": return "google/gemini-2.5-pro"
        default: return modelProvider
        }
    }
}
