import SwiftUI

@main
struct FocusLockApp: App {
    @StateObject private var config = ConfigStore()
    @State private var oauthBanner: String?

    init() {
        BackendManager.shared.start()
        PromptCenter.shared.start()
    }

    var body: some Scene {
        // `Window` (not `WindowGroup`) — single-window app. WindowGroup
        // allowed Cmd+N and macOS state restoration to spawn duplicates.
        Window("Locus", id: "main") {
            ContentView()
                .environmentObject(config)
                .frame(minWidth: 860, minHeight: 560)
                .background(Theme.surface)
                .preferredColorScheme(config.preferredColorScheme)
                .onOpenURL { url in handleOAuthCallback(url) }
                .overlay(alignment: .top) {
                    if let msg = oauthBanner {
                        Text(msg)
                            .font(.system(size: 13, weight: .medium))
                            .padding(.horizontal, 16).padding(.vertical, 10)
                            .background(.thinMaterial, in: Capsule())
                            .padding(.top, 14)
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }
                }
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentMinSize)
    }

    private func handleOAuthCallback(_ url: URL) {
        guard let result = NotionOAuth.parseCallback(url) else { return }
        if let err = result.error, !err.isEmpty {
            showBanner("Notion sign-in failed: \(err)")
            return
        }
        guard !result.token.isEmpty else {
            showBanner("Notion sign-in returned no token.")
            return
        }
        config.applyNotionOAuth(token: result.token, workspace: result.workspace)
        let where_ = result.workspace.isEmpty ? "" : " to \(result.workspace)"
        showBanner("Connected to Notion\(where_). Looking up your database…")

        Task {
            let outcome = await NotionOAuth.discoverDatabases(token: result.token)
            await MainActor.run {
                switch outcome {
                case .found(let options):
                    config.notionAvailableDatabases = options
                    if options.count == 1 {
                        config.notionDatabaseID = options[0].id
                        config.save()
                        showBanner("Connected to Notion\(where_).")
                    } else {
                        // Don't pre-pick anything — force the user to choose
                        // so we don't pull from the wrong DB silently.
                        config.notionDatabaseID = ""
                        config.save()
                        showBanner("Connected — \(options.count) databases found. Pick your planner in Connectors.")
                    }
                case .noAccess:
                    config.notionAvailableDatabases = []
                    showBanner("Notion returned 0 pages. Check your integration has the 'Read content' capability enabled at notion.so/my-integrations, then re-run sign-in.")
                case .pagesButNoDatabase:
                    config.notionAvailableDatabases = []
                    showBanner("Page shared but no database found inside it. Make sure your planner page actually contains an inline database (or share the database directly).")
                }
            }
        }
    }

    private func showBanner(_ msg: String) {
        withAnimation { oauthBanner = msg }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.5) {
            withAnimation { oauthBanner = nil }
        }
    }
}
