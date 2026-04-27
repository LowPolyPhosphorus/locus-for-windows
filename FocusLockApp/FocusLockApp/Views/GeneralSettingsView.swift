import SwiftUI
import AppKit

// MARK: - Settings sub-pages

enum SettingsPage: String, CaseIterable, Identifiable {
    case general      = "General"
    case blocking     = "Blocking"
    case allowlists   = "Allowlists"
    case notifications = "Notifications"
    case advanced     = "Advanced"

    var id: String { rawValue }
    var icon: String {
        switch self {
        case .general:       return "slider.horizontal.3"
        case .blocking:      return "lock.shield"
        case .allowlists:    return "checklist"
        case .notifications: return "bell"
        case .advanced:      return "terminal"
        }
    }
}

// MARK: - Top-level settings view with internal sidebar

struct GeneralSettingsView: View {
    @EnvironmentObject var config: ConfigStore
    @State private var page: SettingsPage = .general

    var body: some View {
        HStack(spacing: 0) {
            // Internal second-level sidebar
            VStack(alignment: .leading, spacing: 2) {
                Text("SETTINGS")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .tracking(1)
                    .padding(.horizontal, 16)
                    .padding(.top, 20)
                    .padding(.bottom, 8)

                ForEach(SettingsPage.allCases) { p in
                    settingsSidebarRow(p)
                }
                Spacer()
            }
            .frame(width: 168)
            .background(Theme.card)
            .overlay(
                Rectangle()
                    .fill(Theme.border)
                    .frame(width: 1),
                alignment: .trailing
            )

            // Page content
            Group {
                switch page {
                case .general:       GeneralPage()
                case .blocking:      BlockingPage()
                case .allowlists:    AllowlistsPage()
                case .notifications: NotificationsPage()
                case .advanced:      AdvancedPage()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func settingsSidebarRow(_ p: SettingsPage) -> some View {
        let sel = page == p
        return Button(action: { page = p }) {
            HStack(spacing: 10) {
                Image(systemName: p.icon)
                    .font(.system(size: 12, weight: .medium))
                    .frame(width: 16)
                    .foregroundStyle(sel ? Theme.accent : .secondary)
                Text(p.rawValue)
                    .font(.system(size: 13, weight: sel ? .semibold : .regular))
                    .foregroundStyle(.primary)
                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 7)
                    .fill(sel ? Theme.accentMuted : Color.clear)
            )
            .padding(.horizontal, 6)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - General page

private struct GeneralPage: View {
    @EnvironmentObject var config: ConfigStore
    @State private var justSaved = false
    @State private var showResetConfirm = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Header(title: "General", subtitle: "Appearance and global preferences.")

                // Appearance
                Card {
                    VStack(alignment: .leading, spacing: 16) {
                        HStack {
                            FieldLabel("Appearance")
                            Spacer()
                            resetButton { config.appearance = ConfigDefaults.appearance }
                        }
                        Picker("", selection: $config.appearance) {
                            Text("System").tag("system")
                            Text("Light").tag("light")
                            Text("Dark").tag("dark")
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()

                        // Accent preview
                        HStack(spacing: 12) {
                            RoundedRectangle(cornerRadius: 6)
                                .fill(Theme.accent)
                                .frame(width: 32, height: 32)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Accent colour")
                                    .font(.system(size: 12, weight: .semibold))
                                Text("Warm amber — fixed")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.top, 4)
                    }
                }

                saveRow(justSaved: $justSaved)

                Spacer(minLength: 32)

                // Destructive reset at the bottom
                Divider().opacity(0.3)
                Button(action: { showResetConfirm = true }) {
                    HStack(spacing: 8) {
                        Image(systemName: "arrow.counterclockwise.circle")
                            .font(.system(size: 14))
                        Text("Reset All Settings")
                            .font(.system(size: 14, weight: .semibold))
                    }
                    .foregroundStyle(.red)
                }
                .buttonStyle(.plain)
                .alert("Reset All Settings?", isPresented: $showResetConfirm) {
                    Button("Reset", role: .destructive) { config.resetAll() }
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text("This will restore every setting to its default value and save to config.json.")
                }
                .padding(.top, 4)
            }
            .padding(32)
            .frame(maxWidth: 640, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

// MARK: - Blocking page

private struct BlockingPage: View {
    @EnvironmentObject var config: ConfigStore
    @State private var justSaved = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Header(title: "Blocking", subtitle: "Timing, polling, and AI strictness.")

                Card {
                    VStack(alignment: .leading, spacing: 18) {
                        // Temporary allow duration
                        HStack {
                            FieldLabel("Temporary Allow Duration")
                            Spacer()
                            resetButton { config.tempAllowMinutes = ConfigDefaults.tempAllowMinutes }
                        }
                        Text("How long a temporary override lasts before the site/app is re-blocked.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                        HStack {
                            Slider(value: Binding(
                                get: { Double(config.tempAllowMinutes) },
                                set: { config.tempAllowMinutes = Int($0) }
                            ), in: 5...120, step: 5)
                            Text("\(config.tempAllowMinutes) min")
                                .font(.system(.body, design: .monospaced))
                                .foregroundStyle(Theme.accent)
                                .frame(width: 70, alignment: .trailing)
                        }

                        Divider().opacity(0.2)

                        // Schedule refresh
                        HStack {
                            FieldLabel("Schedule Refresh")
                            Spacer()
                            resetButton { config.scheduleRefreshMinutes = ConfigDefaults.scheduleRefreshMinutes }
                        }
                        Text("How often Notion events are re-fetched in the background.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                        HStack {
                            Slider(value: Binding(
                                get: { Double(config.scheduleRefreshMinutes) },
                                set: { config.scheduleRefreshMinutes = Int($0) }
                            ), in: 1...60, step: 1)
                            Text("\(config.scheduleRefreshMinutes) min")
                                .font(.system(.body, design: .monospaced))
                                .foregroundStyle(Theme.accent)
                                .frame(width: 70, alignment: .trailing)
                        }

                        Divider().opacity(0.2)

                        // URL poll interval
                        HStack {
                            FieldLabel("URL Poll Interval")
                            Spacer()
                            resetButton { config.urlPollSeconds = ConfigDefaults.urlPollSeconds }
                        }
                        Text("How often Chrome tabs are checked for blocked domains.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                        HStack {
                            Slider(value: Binding(
                                get: { Double(config.urlPollSeconds) },
                                set: { config.urlPollSeconds = Int($0) }
                            ), in: 1...10, step: 1)
                            Text("\(config.urlPollSeconds) s")
                                .font(.system(.body, design: .monospaced))
                                .foregroundStyle(Theme.accent)
                                .frame(width: 50, alignment: .trailing)
                        }

                        Divider().opacity(0.2)

                        // App poll interval
                        HStack {
                            FieldLabel("App Poll Interval")
                            Spacer()
                            resetButton { config.appPollSeconds = ConfigDefaults.appPollSeconds }
                        }
                        Text("How often running GUI apps are checked against the blocklist.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                        HStack {
                            Slider(value: Binding(
                                get: { Double(config.appPollSeconds) },
                                set: { config.appPollSeconds = Int($0) }
                            ), in: 5...60, step: 5)
                            Text("\(config.appPollSeconds) s")
                                .font(.system(.body, design: .monospaced))
                                .foregroundStyle(Theme.accent)
                                .frame(width: 50, alignment: .trailing)
                        }
                    }
                }

                Card {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            FieldLabel("Override Code")
                            Spacer()
                            resetButton { config.overrideCode = ConfigDefaults.overrideCode }
                        }
                        Text("Typed to bypass the lock. Default is \"bob\". Set to the first 100 digits of π for maximum security.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                        SecureField("Override code", text: $config.overrideCode)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.caption, design: .monospaced))
                        Button("Reset to \"bob\"") {
                            config.overrideCode = "bob"
                        }
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.accent)
                        .buttonStyle(.plain)
                    }
                }

                Card {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            FieldLabel("AI Harshness")
                            Spacer()
                            resetButton { config.harshness = ConfigDefaults.harshness }
                        }
                        Text("Controls how strictly the AI evaluates your justifications. Affects the evaluate_reason prompt.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                        Picker("", selection: $config.harshness) {
                            Text("Lenient").tag("Lenient")
                            Text("Standard").tag("Standard")
                            Text("Strict").tag("Strict")
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        Group {
                            switch config.harshness {
                            case "Lenient": Text("More forgiving — gives benefit of the doubt on most reasons.")
                            case "Strict":  Text("Pickier — requires clear, direct relevance to the session subject.")
                            default:        Text("Balanced — default behaviour.")
                            }
                        }
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                }

                saveRow(justSaved: $justSaved)
            }
            .padding(32)
            .frame(maxWidth: 640, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

// MARK: - Allowlists page

private struct AllowlistsPage: View {
    @EnvironmentObject var config: ConfigStore
    @State private var newApp = ""
    @State private var newDomain = ""
    @State private var justSaved = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Header(title: "Allowlists", subtitle: "Always-allowed apps and domains, regardless of session.")

                // Always-allowed apps
                Card {
                    VStack(alignment: .leading, spacing: 12) {
                        FieldLabel("Always-Allowed Apps")
                        Text("These apps are never blocked, even outside the session whitelist. Add the exact process name (e.g. \"Notion\", \"Slack\").")
                            .font(.system(size: 11)).foregroundStyle(.secondary)

                        listEditor(
                            items: $config.alwaysAllowedApps,
                            newItem: $newApp,
                            placeholder: "App name (e.g. Notion)"
                        )
                    }
                }

                // Always-allowed domains
                Card {
                    VStack(alignment: .leading, spacing: 12) {
                        FieldLabel("Always-Allowed Domains")
                        Text("These domains are never blocked in Chrome. Enter bare domains without https:// (e.g. \"schoology.com\").")
                            .font(.system(size: 11)).foregroundStyle(.secondary)

                        listEditor(
                            items: $config.alwaysAllowedDomains,
                            newItem: $newDomain,
                            placeholder: "Domain (e.g. schoology.com)"
                        )
                    }
                }

                saveRow(justSaved: $justSaved)
            }
            .padding(32)
            .frame(maxWidth: 640, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    @ViewBuilder
    private func listEditor(items: Binding<[String]>, newItem: Binding<String>, placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if items.wrappedValue.isEmpty {
                Text("No entries yet.")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 4)
            } else {
                ForEach(Array(items.wrappedValue.enumerated()), id: \.offset) { idx, item in
                    HStack {
                        Text(item)
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(.primary)
                        Spacer()
                        Button(action: { items.wrappedValue.remove(at: idx) }) {
                            Image(systemName: "minus.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(.vertical, 4)
                    if idx < items.wrappedValue.count - 1 {
                        Divider().opacity(0.2)
                    }
                }
            }

            HStack(spacing: 8) {
                TextField(placeholder, text: newItem)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 12, design: .monospaced))
                    .onSubmit { addItem(items: items, newItem: newItem) }
                Button(action: { addItem(items: items, newItem: newItem) }) {
                    Image(systemName: "plus.circle.fill")
                        .foregroundStyle(Theme.accent)
                        .font(.system(size: 18))
                }
                .buttonStyle(.plain)
                .disabled(newItem.wrappedValue.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private func addItem(items: Binding<[String]>, newItem: Binding<String>) {
        let val = newItem.wrappedValue.trimmingCharacters(in: .whitespaces)
        guard !val.isEmpty, !items.wrappedValue.contains(val) else { return }
        items.wrappedValue.append(val)
        newItem.wrappedValue = ""
    }
}

// MARK: - Notifications page

private struct NotificationsPage: View {
    @EnvironmentObject var config: ConfigStore
    @State private var justSaved = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Header(title: "Notifications", subtitle: "Control what macOS notifications Locus sends.")

                Card {
                    VStack(alignment: .leading, spacing: 16) {
                        toggleRow(
                            label: "Show Notifications",
                            subtitle: "Displays banners like \"Evaluating your reason…\" and \"Override accepted\".",
                            value: $config.showNotifications,
                            defaultValue: ConfigDefaults.showNotifications
                        )

                        Divider().opacity(0.2)

                        toggleRow(
                            label: "Play Sound on Block",
                            subtitle: "Plays a system sound when a block is triggered (hook only — requires backend support).",
                            value: $config.playSoundOnBlock,
                            defaultValue: ConfigDefaults.playSoundOnBlock
                        )
                    }
                }

                saveRow(justSaved: $justSaved)
            }
            .padding(32)
            .frame(maxWidth: 640, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private func toggleRow(label: String, subtitle: String, value: Binding<Bool>, defaultValue: Bool) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(label)
                    .font(.system(size: 13, weight: .medium))
                Text(subtitle)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            HStack(spacing: 6) {
                resetButton { value.wrappedValue = defaultValue }
                Toggle("", isOn: value).labelsHidden()
            }
        }
    }
}

// MARK: - Advanced page

private struct AdvancedPage: View {
    @EnvironmentObject var config: ConfigStore
    @State private var justSaved = false

    // Prompt placeholders help text
    private let reasonPlaceholders = "{session_name}, {subject_type}, {subject}, {reason}"
    private let sitePlaceholders = "{session_name}, {domain}, {title_hint}"
    private let titlePlaceholders = "{session_name}, {domain}, {tab_title}"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Header(title: "Advanced", subtitle: "AI prompt overrides, polling, and debug options.")

                // Debug + polling
                Card {
                    VStack(alignment: .leading, spacing: 16) {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Debug Logging")
                                    .font(.system(size: 13, weight: .medium))
                                Text("Enables verbose print output in the Python backend.")
                                    .font(.system(size: 11)).foregroundStyle(.secondary)
                            }
                            Spacer()
                            HStack(spacing: 6) {
                                resetButton { config.debugLogging = ConfigDefaults.debugLogging }
                                Toggle("", isOn: $config.debugLogging).labelsHidden()
                            }
                        }

                        Divider().opacity(0.2)

                        HStack {
                            FieldLabel("URL Poll Interval")
                            Spacer()
                            resetButton { config.urlPollSeconds = ConfigDefaults.urlPollSeconds }
                        }
                        HStack {
                            Slider(value: Binding(
                                get: { Double(config.urlPollSeconds) },
                                set: { config.urlPollSeconds = Int($0) }
                            ), in: 1...10, step: 1)
                            Text("\(config.urlPollSeconds) s")
                                .font(.system(.body, design: .monospaced))
                                .foregroundStyle(Theme.accent)
                                .frame(width: 50, alignment: .trailing)
                        }

                        HStack {
                            FieldLabel("App Poll Interval")
                            Spacer()
                            resetButton { config.appPollSeconds = ConfigDefaults.appPollSeconds }
                        }
                        HStack {
                            Slider(value: Binding(
                                get: { Double(config.appPollSeconds) },
                                set: { config.appPollSeconds = Int($0) }
                            ), in: 5...60, step: 5)
                            Text("\(config.appPollSeconds) s")
                                .font(.system(.body, design: .monospaced))
                                .foregroundStyle(Theme.accent)
                                .frame(width: 50, alignment: .trailing)
                        }
                    }
                }

                // Prompt editors
                promptEditor(
                    label: "Evaluate Reason Prompt",
                    subtitle: "Used when the user submits a justification for a blocked site/app.",
                    placeholders: reasonPlaceholders,
                    value: $config.promptEvaluateReason,
                    defaultValue: ConfigDefaults.evaluateReasonPrompt
                )

                promptEditor(
                    label: "Evaluate Site Relevance Prompt",
                    subtitle: "Used to pre-screen whether a blocked domain is obviously relevant.",
                    placeholders: sitePlaceholders,
                    value: $config.promptEvaluateSite,
                    defaultValue: ConfigDefaults.evaluateSitePrompt
                )

                promptEditor(
                    label: "Evaluate Title Prompt",
                    subtitle: "Used to check if a page title on a temporarily-allowed site is off-topic.",
                    placeholders: titlePlaceholders,
                    value: $config.promptEvaluateTitle,
                    defaultValue: ConfigDefaults.evaluateTitlePrompt
                )

                saveRow(justSaved: $justSaved)
            }
            .padding(32)
            .frame(maxWidth: 640, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private func promptEditor(
        label: String,
        subtitle: String,
        placeholders: String,
        value: Binding<String>,
        defaultValue: String
    ) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        FieldLabel(label)
                        Text(subtitle)
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    Spacer()
                    resetButton { value.wrappedValue = defaultValue }
                }
                Text("Placeholders: \(placeholders)")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 2)
                Text("Leave empty to use the built-in default prompt.")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                TextEditor(text: value)
                    .font(.system(size: 11, design: .monospaced))
                    .frame(minHeight: 120, maxHeight: 200)
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(Theme.border, lineWidth: 1)
                    )
                    .scrollContentBackground(.hidden)
                    .background(Theme.surface)
            }
        }
    }
}

// MARK: - Shared helpers

private func saveRow(justSaved: Binding<Bool>) -> some View {
    SaveRow(justSaved: justSaved)
}

private struct SaveRow: View {
    @EnvironmentObject var config: ConfigStore
    @Binding var justSaved: Bool

    var body: some View {
        HStack(spacing: 14) {
            Button("Save Changes") {
                config.save()
                justSaved = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 2.2) { justSaved = false }
            }
            .buttonStyle(PrimaryButtonStyle())

            Button("Reload from Disk") { config.load() }
                .buttonStyle(SecondaryButtonStyle())

            if justSaved {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.accent)
                    Text("Saved").foregroundStyle(.secondary)
                }
                .font(.system(size: 13, weight: .medium))
                .transition(.opacity)
            }
        }
        .padding(.top, 4)
    }
}

private func resetButton(action: @escaping () -> Void) -> some View {
    Button(action: action) {
        Image(systemName: "arrow.counterclockwise")
            .font(.system(size: 11))
            .foregroundStyle(.secondary)
    }
    .buttonStyle(.plain)
    .help("Reset to default")
}

// MARK: - Shared UI components (used by other views too)

struct Header: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.serif(36))
            Text(subtitle)
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
        }
    }
}

struct FieldLabel: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text)
            .font(.mono(11, medium: true))
            .foregroundStyle(.secondary)
            .textCase(.uppercase)
            .tracking(1.0)
    }
}

struct Card<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        content
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Theme.card)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Theme.border, lineWidth: 1)
            )
    }
}
