import Foundation
import AppKit

// Launches the embedded `locusd` binary as a child process and terminates it
// when the Swift app quits. The backend writes state/command files under
// ~/Library/Application Support/Locus/ — we just keep it running.
final class BackendManager {
    static let shared = BackendManager()

    private var process: Process?
    private var termObserver: NSObjectProtocol?

    private var binaryPath: String? {
        // Bundled inside the .app at Contents/Resources/locusd
        if let p = Bundle.main.path(forResource: "locusd", ofType: nil),
           FileManager.default.isExecutableFile(atPath: p) {
            return p
        }
        return nil
    }

    func start() {
        guard process == nil else { return }
        guard let path = binaryPath else {
            NSLog("[Locus] No bundled locusd binary found — backend will not start.")
            return
        }
        LocusPaths.ensureDirExists()
        LocusPaths.migrateLegacyIfNeeded()

        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        // Line-buffer stdout for timely log output; stream to a log file.
        let logURL = URL(fileURLWithPath: "\(LocusPaths.appSupportDir)/daemon.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let handle = try? FileHandle(forWritingTo: logURL) {
            handle.seekToEndOfFile()
            p.standardOutput = handle
            p.standardError = handle
        }

        do {
            try p.run()
            process = p
            NSLog("[Locus] Started backend pid=\(p.processIdentifier)")
        } catch {
            NSLog("[Locus] Failed to start backend: \(error)")
            return
        }

        // Terminate on app quit
        termObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil, queue: .main
        ) { [weak self] _ in self?.stop() }
    }

    func stop() {
        guard let p = process else { return }
        if p.isRunning {
            p.terminate()
            // Give it a beat to flush, then hard-kill if needed
            let deadline = Date().addingTimeInterval(2)
            while p.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.05)
            }
            if p.isRunning { kill(p.processIdentifier, SIGKILL) }
        }
        process = nil
    }

    var isRunning: Bool {
        process?.isRunning ?? false
    }
}
