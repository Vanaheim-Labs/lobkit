import Foundation

/// Runs shell commands via Process, streaming stdout/stderr line-by-line.
/// All callbacks fire on MainActor so views can observe directly.
@MainActor
final class InstallService: ObservableObject {

    @Published var lastLine: String = ""
    @Published var fullOutput: String = ""

    /// The user's shell PATH, augmented with common Homebrew / nvm locations
    /// so that `node`, `brew`, `openclaw` etc. are found even when launched from .app
    private static let shellPath: String = {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let extras = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "\(home)/.nvm/versions/node/default/bin",
            "\(home)/.nvm/versions/node/current/bin",
            "\(home)/.local/bin",
            "\(home)/.openclaw/bin",
        ]
        let existing = ProcessInfo.processInfo.environment["PATH"] ?? "/usr/bin:/bin"
        return (extras + [existing]).joined(separator: ":")
    }()

    /// Run a command string through /bin/zsh, streaming output line-by-line.
    /// Returns the full combined stdout+stderr and the exit code.
    @discardableResult
    func run(_ command: String) async throws -> (output: String, exitCode: Int32) {
        fullOutput = ""
        lastLine = ""

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-l", "-c", command]
        process.environment = {
            var env = ProcessInfo.processInfo.environment
            env["PATH"] = Self.shellPath
            env["TERM"] = "dumb"
            env["NO_COLOR"] = "1"
            return env
        }()

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        try process.run()

        var accumulated = ""
        let handle = pipe.fileHandleForReading

        // Read in a background task, push lines to MainActor
        let stream = AsyncStream<String> { continuation in
            handle.readabilityHandler = { fh in
                let data = fh.availableData
                if data.isEmpty {
                    continuation.finish()
                    return
                }
                if let str = String(data: data, encoding: .utf8) {
                    continuation.yield(str)
                }
            }
        }

        for await chunk in stream {
            accumulated += chunk
            fullOutput = accumulated
            // Extract last non-empty line for status display
            let lines = chunk.components(separatedBy: .newlines)
            if let last = lines.last(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }) {
                lastLine = last
            }
        }

        handle.readabilityHandler = nil
        process.waitUntilExit()

        return (accumulated, process.terminationStatus)
    }

    /// Run a command and return true if exit code is 0
    func runOk(_ command: String) async -> Bool {
        do {
            let result = try await run(command)
            return result.exitCode == 0
        } catch {
            return false
        }
    }

    /// Run a command and return trimmed stdout, or nil on failure
    func runCapture(_ command: String) async -> String? {
        do {
            let result = try await run(command)
            guard result.exitCode == 0 else { return nil }
            return result.output.trimmingCharacters(in: .whitespacesAndNewlines)
        } catch {
            return nil
        }
    }

    /// Check if a command exists on PATH
    func commandExists(_ cmd: String) async -> Bool {
        await runOk("command -v \(cmd)")
    }
}
