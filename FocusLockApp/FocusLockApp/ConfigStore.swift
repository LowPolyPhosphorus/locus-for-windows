import Foundation
import Combine
import SwiftUI

struct Activity: Equatable {
    var open_apps: [String]
    var allow_apps: [String]
    var allow_domains: [String]
}

struct ICalFeed: Identifiable, Equatable, Hashable {
    let id: UUID = UUID()
    var name: String
    var url: String
}

// Central defaults — used for reset buttons and initial values
struct ConfigDefaults {
    static let tempAllowMinutes       = 15
    static let urlPollSeconds         = 3
    static let appPollSeconds         = 5
    static let scheduleRefreshMinutes = 5
    static let overrideCode           = "bob"
    static let harshness              = "Standard"
    static let appearance             = "system"
    static let showNotifications      = true
    static let playSoundOnBlock       = false
    static let debugLogging           = false
    static let evaluateReasonPrompt   = ""
    static let evaluateSitePrompt     = ""
    static let evaluateTitlePrompt    = ""
}

final class ConfigStore: ObservableObject {
    @Published var notionAPIKey: String = ""
    @Published var notionDatabaseID: String = ""
    @Published var notionEnabled: Bool = false
    // Populated after OAuth — every database the integration can see.
    // Drives the picker in ConnectorsView when there's more than one.
    @Published var notionAvailableDatabases: [NotionOAuth.DBOption] = []

    // iCal subscriptions — list of (name, url) feeds the daemon polls.
    @Published var icalFeeds: [ICalFeed] = []
    @Published var overrideCode: String = ConfigDefaults.overrideCode
    @Published var tempAllowMinutes: Int = ConfigDefaults.tempAllowMinutes
    @Published var urlPollSeconds: Int = ConfigDefaults.urlPollSeconds
    @Published var appPollSeconds: Int = ConfigDefaults.appPollSeconds
    @Published var scheduleRefreshMinutes: Int = ConfigDefaults.scheduleRefreshMinutes
    @Published var activities: [String: Activity] = [:]

    // Appearance
    @Published var appearance: String = ConfigDefaults.appearance

    // Blocking
    @Published var harshness: String = ConfigDefaults.harshness

    // Allowlists
    @Published var alwaysAllowedApps: [String] = []
    @Published var alwaysAllowedDomains: [String] = []

    // Notifications
    @Published var showNotifications: Bool = ConfigDefaults.showNotifications
    @Published var playSoundOnBlock: Bool = ConfigDefaults.playSoundOnBlock

    // Advanced
    @Published var debugLogging: Bool = ConfigDefaults.debugLogging
    @Published var promptEvaluateReason: String = ConfigDefaults.evaluateReasonPrompt
    @Published var promptEvaluateSite: String = ConfigDefaults.evaluateSitePrompt
    @Published var promptEvaluateTitle: String = ConfigDefaults.evaluateTitlePrompt

    private var raw: [String: Any] = [:]
    let configPath: String
    let projectDir: String

    init() {
        self.projectDir = LocusPaths.appSupportDir
        self.configPath = LocusPaths.config
        LocusPaths.ensureDirExists()
        LocusPaths.migrateLegacyIfNeeded()
        load()
    }

    func load() {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: configPath)),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }
        raw = json
        notionAPIKey = (json["api_keys"] as? [String: String])?["notion"] ?? ""
        notionDatabaseID = json["notion_database_id"] as? String ?? ""
        notionEnabled = (json["notion_enabled"] as? Bool)
            ?? (!notionAPIKey.isEmpty && notionAPIKey != "YOUR_NOTION_API_KEY")

        let feeds = (json["ical_feeds"] as? [[String: Any]]) ?? []
        icalFeeds = feeds.compactMap { f in
            guard let url = f["url"] as? String, !url.isEmpty else { return nil }
            return ICalFeed(name: (f["name"] as? String) ?? "", url: url)
        }
        overrideCode = json["override_code"] as? String ?? ConfigDefaults.overrideCode
        tempAllowMinutes = json["temporary_allow_minutes"] as? Int ?? ConfigDefaults.tempAllowMinutes
        urlPollSeconds = json["url_poll_interval_seconds"] as? Int ?? ConfigDefaults.urlPollSeconds
        appPollSeconds = json["app_poll_interval_seconds"] as? Int ?? ConfigDefaults.appPollSeconds
        scheduleRefreshMinutes = json["schedule_refresh_minutes"] as? Int ?? ConfigDefaults.scheduleRefreshMinutes

        appearance = json["appearance"] as? String ?? ConfigDefaults.appearance
        harshness = json["harshness"] as? String ?? ConfigDefaults.harshness
        alwaysAllowedApps = json["always_allowed_apps"] as? [String] ?? []
        alwaysAllowedDomains = json["always_allowed_domains"] as? [String] ?? []
        showNotifications = json["show_notifications"] as? Bool ?? ConfigDefaults.showNotifications
        playSoundOnBlock = json["play_sound_on_block"] as? Bool ?? ConfigDefaults.playSoundOnBlock
        debugLogging = json["debug_logging"] as? Bool ?? ConfigDefaults.debugLogging

        if let prompts = json["prompts"] as? [String: String] {
            promptEvaluateReason = prompts["evaluate_reason"] ?? ConfigDefaults.evaluateReasonPrompt
            promptEvaluateSite = prompts["evaluate_site_relevance"] ?? ConfigDefaults.evaluateSitePrompt
            promptEvaluateTitle = prompts["evaluate_title"] ?? ConfigDefaults.evaluateTitlePrompt
        }

        if let acts = json["activities"] as? [String: [String: Any]] {
            var out: [String: Activity] = [:]
            for (k, v) in acts {
                out[k] = Activity(
                    open_apps: v["open_apps"] as? [String] ?? [],
                    allow_apps: v["allow_apps"] as? [String] ?? [],
                    allow_domains: v["allow_domains"] as? [String] ?? []
                )
            }
            activities = out
        }
    }

    func save() {
        var out = raw
        var keys = (out["api_keys"] as? [String: String]) ?? [:]
        keys["notion"] = notionAPIKey
        out["api_keys"] = keys
        out["notion_database_id"] = notionDatabaseID
        out["notion_enabled"] = notionEnabled

        out["ical_feeds"] = icalFeeds.map { ["name": $0.name, "url": $0.url] }
        out["override_code"] = overrideCode
        out["temporary_allow_minutes"] = tempAllowMinutes
        out["url_poll_interval_seconds"] = urlPollSeconds
        out["app_poll_interval_seconds"] = appPollSeconds
        out["schedule_refresh_minutes"] = scheduleRefreshMinutes

        out["appearance"] = appearance
        out["harshness"] = harshness
        out["always_allowed_apps"] = alwaysAllowedApps
        out["always_allowed_domains"] = alwaysAllowedDomains
        out["show_notifications"] = showNotifications
        out["play_sound_on_block"] = playSoundOnBlock
        out["debug_logging"] = debugLogging
        out["prompts"] = [
            "evaluate_reason": promptEvaluateReason,
            "evaluate_site_relevance": promptEvaluateSite,
            "evaluate_title": promptEvaluateTitle,
        ]

        var acts: [String: [String: Any]] = [:]
        for (k, v) in activities {
            acts[k] = [
                "open_apps": v.open_apps,
                "allow_apps": v.allow_apps,
                "allow_domains": v.allow_domains,
            ]
        }
        out["activities"] = acts
        raw = out

        let opts: JSONSerialization.WritingOptions = [.prettyPrinted, .sortedKeys]
        if let data = try? JSONSerialization.data(withJSONObject: out, options: opts) {
            try? data.write(to: URL(fileURLWithPath: configPath))
        }
    }

    func resetAll() {
        overrideCode = ConfigDefaults.overrideCode
        tempAllowMinutes = ConfigDefaults.tempAllowMinutes
        urlPollSeconds = ConfigDefaults.urlPollSeconds
        appPollSeconds = ConfigDefaults.appPollSeconds
        scheduleRefreshMinutes = ConfigDefaults.scheduleRefreshMinutes
        appearance = ConfigDefaults.appearance
        harshness = ConfigDefaults.harshness
        alwaysAllowedApps = []
        alwaysAllowedDomains = []
        showNotifications = ConfigDefaults.showNotifications
        playSoundOnBlock = ConfigDefaults.playSoundOnBlock
        debugLogging = ConfigDefaults.debugLogging
        promptEvaluateReason = ConfigDefaults.evaluateReasonPrompt
        promptEvaluateSite = ConfigDefaults.evaluateSitePrompt
        promptEvaluateTitle = ConfigDefaults.evaluateTitlePrompt
        // Disable Notion on reset — leaving it enabled with stale creds
        // half-configured is worse than off. Creds themselves stay put so
        // the user can flip notionEnabled back on without re-entering them.
        notionEnabled = false
        save()
    }

    var preferredColorScheme: ColorScheme? {
        switch appearance {
        case "light": return .light
        case "dark":  return .dark
        default:      return nil
        }
    }

    var sortedClassNames: [String] {
        activities.keys.sorted()
    }

    func applyNotionOAuth(token: String, workspace: String) {
        notionAPIKey = token
        notionEnabled = !token.isEmpty
        save()
        notifyNotionChanged()
    }

    /// Tell the running daemon to rebuild its Notion client. Without this,
    /// the daemon keeps using the credentials it loaded at startup and
    /// ignores any key / database-id change written to config.json.
    func notifyNotionChanged() {
        let cmd: [String: Any] = ["type": "reconnect_notion", "data": [:]]
        guard let json = try? JSONSerialization.data(withJSONObject: cmd) else { return }
        try? json.write(to: URL(fileURLWithPath: LocusPaths.command), options: .atomic)
    }

    /// Re-fetch the list of databases the integration can see. Runs in the
    /// background — the picker in Connectors waits for this to populate so
    /// returning users see their options after a fresh launch.
    func refreshNotionDatabases() {
        let token = notionAPIKey
        guard !token.isEmpty else {
            notionAvailableDatabases = []
            return
        }
        Task {
            let outcome = await NotionOAuth.discoverDatabases(token: token)
            await MainActor.run {
                if case .found(let opts) = outcome {
                    self.notionAvailableDatabases = opts
                } else {
                    self.notionAvailableDatabases = []
                }
            }
        }
    }

    func notifyICalChanged() {
        let cmd: [String: Any] = ["type": "reconnect_ical", "data": [:]]
        guard let json = try? JSONSerialization.data(withJSONObject: cmd) else { return }
        try? json.write(to: URL(fileURLWithPath: LocusPaths.command), options: .atomic)
    }
}
