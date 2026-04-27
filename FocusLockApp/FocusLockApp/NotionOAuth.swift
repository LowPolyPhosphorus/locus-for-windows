import Foundation
import AppKit

// Notion OAuth wiring. The Cloudflare Worker (cloudflare_worker/worker.js)
// holds NOTION_CLIENT_SECRET and exchanges the code; we only need the public
// client ID and the redirect URI (which must match what's registered on the
// Notion integration AND what's hardcoded in worker.js).
enum NotionOAuth {
    // Public client ID from your Notion integration settings.
    // See cloudflare_worker/DEPLOY.md for setup.
    static let clientID = "34ad872b-594c-81a3-be0a-00376b27f521"

    // Must match NOTION_REDIRECT_URI in cloudflare_worker/worker.js exactly.
    static let redirectURI = "https://locus-proxy.locus-proxy.workers.dev/oauth/notion"

    static var authorizeURL: URL? {
        var c = URLComponents(string: "https://api.notion.com/v1/oauth/authorize")!
        c.queryItems = [
            URLQueryItem(name: "client_id", value: clientID),
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "owner", value: "user"),
            URLQueryItem(name: "redirect_uri", value: redirectURI),
        ]
        return c.url
    }

    static var isConfigured: Bool {
        clientID != "YOUR_NOTION_CLIENT_ID" && !clientID.isEmpty
    }

    static func startSignIn() {
        guard let url = authorizeURL else { return }
        NSWorkspace.shared.open(url)
    }

    struct Result {
        let token: String
        let workspace: String
        let error: String?
    }

    /// Parse an inbound `locus://oauth/notion?token=…&workspace=…` URL.
    static func parseCallback(_ url: URL) -> Result? {
        guard url.scheme == "locus", url.host == "oauth", url.path == "/notion" else {
            return nil
        }
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let dict = Dictionary(uniqueKeysWithValues: items.map { ($0.name, $0.value ?? "") })
        return Result(
            token: dict["token"] ?? "",
            workspace: dict["workspace"] ?? "",
            error: dict["error"]
        )
    }

    /// Ask Notion for the databases this OAuth token has access to. With OAuth,
    /// the user picks exactly which pages/databases to share during consent, so
    /// usually this returns a single ID and we don't need to ask the user.
    struct DBOption: Identifiable, Equatable, Hashable {
        let id: String
        let title: String
    }

    enum DiscoveryResult {
        case found([DBOption])     // 1+ databases the integration can see
        case noAccess              // search returned 0 — integration lacks read_content or shared nothing
        case pagesButNoDatabase    // pages shared, no child_database under any of them
    }

    static func discoverDatabases(token: String) async -> DiscoveryResult {
        var found: [DBOption] = []
        var seenIDs: Set<String> = []

        // 1. Directly-shared databases.
        for db in await searchDatabases(token: token) {
            if seenIDs.insert(db.id).inserted { found.append(db) }
        }

        // 2. BFS through shared pages — students often nest a planner DB
        // inside a "Planner" page (in columns, toggles, sub-pages…).
        let pages = await allResultIDs(token: token, objectFilter: "page")
        for pageID in pages {
            for db in await childDatabases(token: token, rootBlockID: pageID) {
                if seenIDs.insert(db.id).inserted { found.append(db) }
            }
        }

        if !found.isEmpty { return .found(found) }
        if pages.isEmpty { return .noAccess }
        return .pagesButNoDatabase
    }

    private static func searchRequest(token: String, objectFilter: String) -> URLRequest? {
        guard let url = URL(string: "https://api.notion.com/v1/search") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("2022-06-28", forHTTPHeaderField: "Notion-Version")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "filter": ["value": objectFilter, "property": "object"],
            "page_size": 50,
        ])
        return req
    }

    private static func firstResultID(token: String, objectFilter: String) async -> String? {
        guard let req = searchRequest(token: token, objectFilter: objectFilter),
              let (data, _) = try? await URLSession.shared.data(for: req),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let results = json["results"] as? [[String: Any]] else {
            return nil
        }
        return results.compactMap { $0["id"] as? String }.first
    }

    /// Search for databases and return id+title for each.
    private static func searchDatabases(token: String) async -> [DBOption] {
        guard let req = searchRequest(token: token, objectFilter: "database"),
              let (data, _) = try? await URLSession.shared.data(for: req),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let results = json["results"] as? [[String: Any]] else {
            return []
        }
        return results.compactMap { result in
            guard let id = result["id"] as? String else { return nil }
            let title = extractDatabaseTitle(result) ?? "Untitled"
            return DBOption(id: id, title: title)
        }
    }

    /// Pull the human-readable title out of a database object's `title` array.
    private static func extractDatabaseTitle(_ db: [String: Any]) -> String? {
        guard let arr = db["title"] as? [[String: Any]] else { return nil }
        let pieces = arr.compactMap { $0["plain_text"] as? String }
        let joined = pieces.joined()
        return joined.isEmpty ? nil : joined
    }

    private static func allResultIDs(token: String, objectFilter: String) async -> [String] {
        guard let req = searchRequest(token: token, objectFilter: objectFilter),
              let (data, _) = try? await URLSession.shared.data(for: req),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let results = json["results"] as? [[String: Any]] else {
            return []
        }
        return results.compactMap { $0["id"] as? String }
    }

    /// BFS through a block tree collecting every child_database we can see.
    /// Direct `/v1/blocks/{id}/children` only returns immediate children, so
    /// we descend into containers (columns, toggles, sub-pages, etc.).
    private static func childDatabases(token: String, rootBlockID: String) async -> [DBOption] {
        var queue: [String] = [rootBlockID]
        var visited: Set<String> = [rootBlockID]
        var hops = 0
        let maxHops = 80
        var out: [DBOption] = []

        while !queue.isEmpty && hops < maxHops {
            let parent = queue.removeFirst()
            hops += 1
            guard let blocks = await fetchChildren(token: token, blockID: parent) else {
                continue
            }
            for block in blocks {
                guard let type = block["type"] as? String else { continue }
                if type == "child_database" || type == "database" {
                    if let id = block["id"] as? String {
                        let title = (block["child_database"] as? [String: Any])?["title"] as? String
                            ?? "Untitled"
                        out.append(DBOption(id: id, title: title))
                    }
                    continue
                }
                // Linked databases live as link_to_page blocks pointing at a
                // database_id. The integration may or may not have access to
                // the original — only way to know is to try fetching it.
                if type == "link_to_page",
                   let link = block["link_to_page"] as? [String: Any],
                   let linkType = link["type"] as? String {
                    if linkType == "database_id", let dbID = link["database_id"] as? String {
                        if let opt = await fetchDatabaseOption(token: token, databaseID: dbID) {
                            out.append(opt)
                        }
                    } else if linkType == "page_id", let pageID = link["page_id"] as? String,
                              !visited.contains(pageID) {
                        visited.insert(pageID)
                        queue.append(pageID)
                    }
                    continue
                }
                let hasChildren = block["has_children"] as? Bool ?? false
                let descendable: Set<String> = [
                    "child_page", "toggle", "column_list", "column",
                    "synced_block", "callout", "quote", "bulleted_list_item",
                    "numbered_list_item", "to_do", "template",
                ]
                if hasChildren, descendable.contains(type),
                   let id = block["id"] as? String, !visited.contains(id) {
                    visited.insert(id)
                    queue.append(id)
                }
            }
        }
        return out
    }

    /// GET /v1/databases/{id}. Returns nil if the integration doesn't have
    /// access (404) — common case for linked databases where the original
    /// lives outside the OAuth grant.
    private static func fetchDatabaseOption(token: String, databaseID: String) async -> DBOption? {
        guard let url = URL(string: "https://api.notion.com/v1/databases/\(databaseID)") else {
            return nil
        }
        var req = URLRequest(url: url)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("2022-06-28", forHTTPHeaderField: "Notion-Version")
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = json["id"] as? String else {
            return nil
        }
        let title = extractDatabaseTitle(json) ?? "Untitled"
        return DBOption(id: id, title: title)
    }

    private static func fetchChildren(token: String, blockID: String) async -> [[String: Any]]? {
        guard let url = URL(string: "https://api.notion.com/v1/blocks/\(blockID)/children?page_size=100") else {
            return nil
        }
        var req = URLRequest(url: url)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("2022-06-28", forHTTPHeaderField: "Notion-Version")
        guard let (data, _) = try? await URLSession.shared.data(for: req),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return json["results"] as? [[String: Any]]
    }
}
