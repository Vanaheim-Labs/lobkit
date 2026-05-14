import Foundation

/// Result of running a shell command
struct ShellResult: Sendable {
    let exitCode: Int32
    let output: String
}

/// Service that runs shell commands asynchronously with proper PATH setup
actor InstallService {
    static let shared = InstallService()

    /// PATH that includes common install locations for node, openclaw, homebrew, etc.
    private var shellPATH: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let extra = [
            "\(home)/.nvm/versions/node/v24.14.0/bin",
            "\(home)/.nvm/versions/node/v22.16.0/bin",
            "\(home)/.local/bin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
        let current = ProcessInfo.processInfo.environment["PATH"] ?? ""
        // Prepend extra paths, dedup later doesn't matter
        return (extra + current.split(separator: ":").map(String.init)).joined(separator: ":")
    }

    /// Run a command and return the full output when done.
    func run(_ command: String, arguments: [String] = []) async -> ShellResult {
        let process = Process()
        let pipe = Pipe()

        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-l", "-c", ([command] + arguments).joined(separator: " ")]
        process.standardOutput = pipe
        process.standardError = pipe
        process.environment = buildEnvironment()

        do {
            try process.run()
        } catch {
            return ShellResult(exitCode: -1, output: "Failed to launch: \(error.localizedDescription)")
        }

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return ShellResult(exitCode: process.terminationStatus, output: output)
    }

    /// Run a command and stream output line-by-line via an AsyncStream.
    func runStreaming(_ command: String) -> (stream: AsyncStream<String>, task: Task<Int32, Never>) {
        let (stream, continuation) = AsyncStream<String>.makeStream()

        let env = buildEnvironment()
        let task = Task<Int32, Never> { [env] in
            let process = Process()
            let pipe = Pipe()

            process.executableURL = URL(fileURLWithPath: "/bin/bash")
            process.arguments = ["-l", "-c", command]
            process.standardOutput = pipe
            process.standardError = pipe
            process.environment = env

            do {
                try process.run()
            } catch {
                continuation.yield("Failed to launch: \(error.localizedDescription)")
                continuation.finish()
                return -1
            }

            let handle = pipe.fileHandleForReading
            // Read in a background thread to avoid blocking
            let readTask = Task.detached {
                var buffer = Data()
                while true {
                    let chunk = handle.availableData
                    if chunk.isEmpty { break }
                    buffer.append(chunk)
                    // Emit complete lines
                    while let newlineRange = buffer.range(of: Data([0x0A])) {
                        let lineData = buffer.subdata(in: buffer.startIndex..<newlineRange.lowerBound)
                        buffer.removeSubrange(buffer.startIndex...newlineRange.lowerBound)
                        if let line = String(data: lineData, encoding: .utf8) {
                            continuation.yield(line)
                        }
                    }
                }
                // Emit any remaining data
                if !buffer.isEmpty, let line = String(data: buffer, encoding: .utf8) {
                    continuation.yield(line)
                }
            }

            process.waitUntilExit()
            await readTask.value
            continuation.finish()
            return process.terminationStatus
        }

        return (stream, task)
    }

    private func buildEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = shellPATH
        // Ensure non-interactive
        env["TERM"] = "dumb"
        env.removeValue(forKey: "TERM_PROGRAM")
        return env
    }
}
