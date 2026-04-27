import Foundation
import AppKit
import SwiftUI

/// Bridges the Python daemon's prompt.json file to a styled SwiftUI panel.
/// Polls the file every ~0.25s; when a new prompt arrives it surfaces a
/// floating NSPanel and writes the user's response back to response.json.
final class PromptCenter: NSObject, ObservableObject {
    static let shared = PromptCenter()

    @Published var current: Prompt?

    private var timer: Timer?
    private var lastSeenID: String?
    private var panel: NSPanel?

    func start() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            self?.poll()
        }
    }

    private func poll() {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: LocusPaths.prompt)),
              let prompt = try? JSONDecoder().decode(Prompt.self, from: data) else {
            return
        }
        if prompt.id == lastSeenID { return }
        lastSeenID = prompt.id
        DispatchQueue.main.async { self.present(prompt) }
    }

    private func present(_ prompt: Prompt) {
        // If a previous panel is still up (rare — daemon serializes prompts),
        // tear it down before opening the new one.
        panel?.close()
        panel = nil
        current = prompt

        let host = NSHostingController(rootView: PromptView(prompt: prompt))
        host.view.frame = NSRect(x: 0, y: 0, width: 460, height: 1)
        host.view.layoutSubtreeIfNeeded()

        let panel = NSPanel(
            contentViewController: host
        )
        panel.styleMask = [.titled, .fullSizeContentView]
        panel.titlebarAppearsTransparent = true
        panel.titleVisibility = .hidden
        panel.isMovableByWindowBackground = true
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.standardWindowButton(.closeButton)?.isHidden = true
        panel.standardWindowButton(.miniaturizeButton)?.isHidden = true
        panel.standardWindowButton(.zoomButton)?.isHidden = true
        panel.isReleasedWhenClosed = false
        panel.center()

        self.panel = panel
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
    }

    /// Called by PromptView when the user picks an action.
    func respond(_ resp: PromptResponse) {
        var dict: [String: Any] = ["id": resp.id, "action": resp.action]
        if !resp.reason.isEmpty { dict["reason"] = resp.reason }
        if !resp.code.isEmpty { dict["code"] = resp.code }

        if let data = try? JSONSerialization.data(withJSONObject: dict) {
            let url = URL(fileURLWithPath: LocusPaths.response)
            try? data.write(to: url, options: .atomic)
        }

        panel?.close()
        panel = nil
        current = nil
    }
}

// MARK: - Prompt schema (mirrors Python side in dialogs.py)

struct Prompt: Decodable, Identifiable, Equatable {
    let id: String
    let type: String

    let blocked_name: String?
    let blocked_type: String?      // "app" | "website" | "website content"
    let session_name: String?
    let tab_title: String?
    let ai_reason: String?
    let approved: Bool?
    let explanation: String?
    let target_name: String?
    let minutes: Int?
    let is_pi_hint: Bool?
}

struct PromptResponse {
    let id: String
    let action: String   // "submit" | "override" | "cancel" | "ok"
    var reason: String = ""
    var code: String = ""
}
