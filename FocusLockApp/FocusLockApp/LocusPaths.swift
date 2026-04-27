import Foundation

// Canonical on-disk paths for Locus, mirrored from focuslock/paths.py.
// Everything lives under ~/Library/Application Support/Locus/ so the app is
// ship-ready: no hardcoded ~/Desktop/focus paths, no /tmp/ files.
enum LocusPaths {
    static let appSupportDir: String = {
        let home = NSHomeDirectory()
        return "\(home)/Library/Application Support/Locus"
    }()

    static var config: String    { "\(appSupportDir)/config.json" }
    static var state: String     { "\(appSupportDir)/state.json" }
    static var command: String   { "\(appSupportDir)/command.json" }
    static var analytics: String { "\(appSupportDir)/analytics.json" }
    static var events: String    { "\(appSupportDir)/events.jsonl" }
    static var prompt: String    { "\(appSupportDir)/prompt.json" }
    static var response: String  { "\(appSupportDir)/response.json" }

    static func ensureDirExists() {
        try? FileManager.default.createDirectory(
            atPath: appSupportDir,
            withIntermediateDirectories: true
        )
    }

    // Copy any files from old locations if the new ones don't exist yet.
    // Idempotent — safe to call on every launch.
    static func migrateLegacyIfNeeded() {
        let home = NSHomeDirectory()
        let migrations: [(new: String, old: String)] = [
            (config,    "\(home)/Desktop/focus/config.json"),
            (state,     "/tmp/focuslock_state.json"),
            (command,   "/tmp/focuslock_command.json"),
            (analytics, "/tmp/focuslock_analytics.json"),
            (events,    "/tmp/focuslock_events.jsonl"),
        ]
        let fm = FileManager.default
        for m in migrations {
            if fm.fileExists(atPath: m.new) { continue }
            if !fm.fileExists(atPath: m.old) { continue }
            try? fm.copyItem(atPath: m.old, toPath: m.new)
        }
    }
}
