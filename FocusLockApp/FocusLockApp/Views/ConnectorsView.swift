import SwiftUI

struct ConnectorsView: View {
    @EnvironmentObject var config: ConfigStore
    @State private var selected: String = "notion"
    @State private var justSaved: Bool = false
    @State private var manualID: String = ""
    @State private var newFeedName: String = ""
    @State private var newFeedURL: String = ""

    // For future connectors, add more entries here.
    private let connectors: [ConnectorMeta] = [
        ConnectorMeta(
            id: "notion",
            name: "Notion",
            subtitle: "Pull assignments from your planner database.",
            icon: "doc.text.fill"
        ),
        ConnectorMeta(
            id: "ical",
            name: "Calendar (iCal)",
            subtitle: "Subscribe to any iCal feed — Google, Apple, Outlook, school calendars.",
            icon: "calendar"
        ),
    ]

    var body: some View {
        HStack(spacing: 0) {
            list
                .frame(width: 240)
                .background(Theme.surface)

            Divider()

            detail
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private var list: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Connectors")
                .font(.serif(26))
                .padding(.horizontal, 18)
                .padding(.top, 22)
                .padding(.bottom, 14)

            ScrollView {
                VStack(spacing: 4) {
                    ForEach(connectors) { c in
                        connectorRow(c)
                    }
                }
                .padding(.horizontal, 10)
            }
        }
    }

    private func connectorRow(_ c: ConnectorMeta) -> some View {
        let isSelected = selected == c.id
        let isOn = isEnabled(c.id)
        return Button { selected = c.id } label: {
            HStack(spacing: 10) {
                Image(systemName: c.icon)
                    .font(.system(size: 13))
                    .foregroundStyle(isSelected ? Theme.accent : .secondary)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 1) {
                    Text(c.name)
                        .font(.system(size: 14, weight: isSelected ? .semibold : .regular))
                    Text(isOn ? "Connected" : "Not connected")
                        .font(.system(size: 11))
                        .foregroundStyle(isOn ? Theme.accent : .secondary)
                }
                Spacer()
                Circle()
                    .fill(isOn ? Color.green : .secondary.opacity(0.35))
                    .frame(width: 7, height: 7)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(isSelected ? Theme.accentMuted : Color.clear)
            )
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var detail: some View {
        switch selected {
        case "notion": notionDetail
        case "ical": icalDetail
        default: Text("Select a connector").foregroundStyle(.secondary)
        }
    }

    private var notionDetail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Header(title: "Notion", subtitle: "Connect your Notion planner to auto-populate focus sessions.")

                Card {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Enable Notion")
                                    .font(.system(size: 14, weight: .semibold))
                                Text("When off, FocusLock works entirely from custom tasks.")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Toggle("", isOn: $config.notionEnabled)
                                .labelsHidden()
                                .toggleStyle(.switch)
                        }
                    }
                }

                Card {
                    VStack(alignment: .leading, spacing: 14) {
                        FieldLabel("Account")
                        if config.notionAPIKey.isEmpty {
                            Button {
                                NotionOAuth.startSignIn()
                            } label: {
                                HStack(spacing: 8) {
                                    Image(systemName: "arrow.up.right.square")
                                    Text("Sign in with Notion")
                                }
                            }
                            .buttonStyle(PrimaryButtonStyle())
                            .disabled(!NotionOAuth.isConfigured)

                            if !NotionOAuth.isConfigured {
                                Text("OAuth not configured. See cloudflare_worker/DEPLOY.md to set up your Notion integration, then edit NotionOAuth.swift.")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            } else {
                                Text("Opens Notion in your browser. After authorizing, you'll bounce back to Locus.")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                        } else {
                            HStack(spacing: 8) {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundStyle(Theme.accent)
                                Text("Connected").font(.system(size: 13, weight: .medium))
                                Spacer()
                                Button("Disconnect") {
                                    config.notionAPIKey = ""
                                    config.notionEnabled = false
                                    config.notionDatabaseID = ""
                                    config.notionAvailableDatabases = []
                                    config.save()
                                    config.notifyNotionChanged()
                                }
                                .buttonStyle(.borderless)
                            }
                        }
                    }
                }

                if !config.notionAPIKey.isEmpty {
                    databasePicker
                }

                HStack(spacing: 14) {
                    Button("Save Changes") {
                        config.save()
                        justSaved = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2.2) {
                            justSaved = false
                        }
                    }
                    .buttonStyle(PrimaryButtonStyle())

                    if justSaved {
                        HStack(spacing: 6) {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(Theme.accent)
                            Text("Saved").foregroundStyle(.secondary)
                        }
                        .font(.system(size: 13, weight: .medium))
                    }
                }
            }
            .padding(32)
            .frame(maxWidth: 720, alignment: .leading)
        }
        .onAppear {
            // Returning users land here without an in-memory db list (it's
            // not persisted to disk); re-query Notion to populate the picker.
            if !config.notionAPIKey.isEmpty && config.notionAvailableDatabases.isEmpty {
                config.refreshNotionDatabases()
            }
        }
    }

    @ViewBuilder
    private var databasePicker: some View {
        let options = config.notionAvailableDatabases
        let manuallySet = options.isEmpty && !config.notionDatabaseID.isEmpty
        Card {
            VStack(alignment: .leading, spacing: 12) {
                FieldLabel("Planner Database")

                if manuallySet {
                    // User pasted a database ID directly — no need to scold
                    // them about discovery anymore.
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(Theme.accent)
                        Text("Using manually-entered database")
                            .font(.system(size: 13, weight: .medium))
                        Spacer()
                        Button("Change") {
                            config.notionDatabaseID = ""
                            config.save()
                            config.notifyNotionChanged()
                        }
                        .buttonStyle(.borderless)
                    }
                    Text(config.notionDatabaseID)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                } else if options.isEmpty {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                        Text("No databases auto-discovered")
                            .font(.system(size: 13, weight: .semibold))
                    }
                    Text("This usually means your Planner page references a *linked* database that lives elsewhere. Paste your database ID below — open the database in Notion, copy the URL, the ID is the 32-character hex chunk before the `?v=`.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)

                    HStack(spacing: 8) {
                        TextField("paste database URL or ID", text: $manualID)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 12, design: .monospaced))
                        Button("Use") {
                            if let id = extractNotionID(manualID) {
                                config.notionDatabaseID = id
                                config.save()
                                config.notifyNotionChanged()
                                manualID = ""
                            }
                        }
                        .disabled(extractNotionID(manualID) == nil)
                    }
                } else {
                    Picker("", selection: Binding(
                        get: { config.notionDatabaseID },
                        set: { newID in
                            config.notionDatabaseID = newID
                            config.save()
                            config.notifyNotionChanged()
                        }
                    )) {
                        Text("— Select a database —").tag("")
                        ForEach(options) { opt in
                            Text(opt.title).tag(opt.id)
                        }
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()

                    if config.notionDatabaseID.isEmpty {
                        Text("Pick the database Locus should pull assignments from.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    } else {
                        Text("Locus will pull upcoming assignments from this database.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var icalDetail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Header(
                    title: "Calendar (iCal)",
                    subtitle: "Paste the secret iCal URL from any calendar provider — Google, Apple, Outlook, Schoology, school district calendars."
                )

                Card {
                    VStack(alignment: .leading, spacing: 14) {
                        FieldLabel("Where to find your URL")
                        Text("• Google Calendar: Settings → your calendar → Integrate calendar → \"Secret address in iCal format.\"\n• Apple iCloud: calendar.icloud.com → click your calendar → Public Calendar → copy URL.\n• Outlook: Settings → Calendar → Shared calendars → Publish a calendar → ICS link.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                Card {
                    VStack(alignment: .leading, spacing: 14) {
                        FieldLabel("Subscribed feeds")
                        if config.icalFeeds.isEmpty {
                            Text("No feeds yet. Add one below.")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(config.icalFeeds) { feed in
                                feedRow(feed)
                            }
                        }
                    }
                }

                Card {
                    VStack(alignment: .leading, spacing: 12) {
                        FieldLabel("Add a feed")
                        TextField("Nickname (e.g. School)", text: $newFeedName)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 13))
                        TextField("https://… or webcal://… URL", text: $newFeedURL)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 12, design: .monospaced))
                        HStack {
                            Spacer()
                            Button("Add Feed") {
                                let url = newFeedURL.trimmingCharacters(in: .whitespacesAndNewlines)
                                guard !url.isEmpty else { return }
                                let feed = ICalFeed(
                                    name: newFeedName.trimmingCharacters(in: .whitespaces),
                                    url: url
                                )
                                config.icalFeeds.append(feed)
                                config.save()
                                config.notifyICalChanged()
                                newFeedName = ""
                                newFeedURL = ""
                            }
                            .buttonStyle(PrimaryButtonStyle())
                            .disabled(newFeedURL.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                    }
                }
            }
            .padding(32)
            .frame(maxWidth: 720, alignment: .leading)
        }
    }

    private func feedRow(_ feed: ICalFeed) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "calendar")
                .foregroundStyle(Theme.accent)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(feed.name.isEmpty ? "Untitled feed" : feed.name)
                    .font(.system(size: 13, weight: .medium))
                Text(feed.url)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer()
            Button {
                config.icalFeeds.removeAll { $0.id == feed.id }
                config.save()
                config.notifyICalChanged()
            } label: {
                Image(systemName: "trash")
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.borderless)
        }
        .padding(.vertical, 4)
    }

    /// Pull a 32-char hex Notion object ID out of a URL or raw paste.
    /// Notion IDs are 32 hex chars (sometimes dash-separated as 8-4-4-4-12).
    private func extractNotionID(_ raw: String) -> String? {
        let stripped = raw.replacingOccurrences(of: "-", with: "")
        // Find the longest run of 32 hex characters anywhere in the input.
        let scalars = Array(stripped.unicodeScalars)
        let isHex: (Unicode.Scalar) -> Bool = { s in
            (s >= "0" && s <= "9") || (s >= "a" && s <= "f") || (s >= "A" && s <= "F")
        }
        var i = 0
        while i + 32 <= scalars.count {
            let slice = scalars[i..<(i+32)]
            if slice.allSatisfy(isHex) {
                return String(String.UnicodeScalarView(slice)).lowercased()
            }
            i += 1
        }
        return nil
    }

    private func isEnabled(_ id: String) -> Bool {
        switch id {
        case "notion": return config.notionEnabled && !config.notionAPIKey.isEmpty
        case "ical": return !config.icalFeeds.isEmpty
        default: return false
        }
    }
}

private struct ConnectorMeta: Identifiable {
    let id: String
    let name: String
    let subtitle: String
    let icon: String
}
