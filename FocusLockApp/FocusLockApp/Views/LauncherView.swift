import SwiftUI

// MARK: – State models

private struct BackendEvent: Codable, Identifiable {
    let title: String
    let class_name: String
    let event_type: String
    let date: String
    let note: String
    let start_time: String?    // "HH:MM" 24h, when present (calendar timed events)
    let source: String?        // "notion" | "google", for icon hints
    var id: String { "\(source ?? "")|\(title)|\(date)|\(start_time ?? "")" }
}

private struct BackendSession: Codable {
    let title: String
    let class_name: String
    let event_type: String
    let display_name: String
}

private struct BackendState: Codable {
    let events: [BackendEvent]
    let session: BackendSession?
    let updated_at: Double
}

// MARK: – View

struct LauncherView: View {
    @EnvironmentObject var config: ConfigStore
    @State private var isRunning = false
    @State private var events: [BackendEvent] = []
    @State private var session: BackendSession? = nil
    @State private var selectedIndex: Int? = nil
    @State private var pollTimer: Timer?
    @State private var customTask: String = ""

    private var statePath: String   { LocusPaths.state }
    private var commandPath: String { LocusPaths.command }

    var body: some View {
        VStack(spacing: 0) {
            Spacer().frame(height: 28)

            // Lock icon
            ZStack {
                Circle()
                    .fill(session != nil ? Color.red.opacity(0.1) : Theme.accentMuted)
                    .frame(width: 100, height: 100)
                Image(systemName: session != nil ? "lock.fill" : "lock.open.fill")
                    .font(.system(size: 44, weight: .semibold))
                    .foregroundStyle(session != nil ? .red : Theme.accent)
            }

            Text("Locus")
                .font(.serif(48))
                .padding(.top, 16)

            // Status line
            Group {
                if let s = session {
                    HStack(spacing: 6) {
                        Circle().fill(.red).frame(width: 8, height: 8)
                        Text(s.display_name)
                            .font(.system(size: 15, weight: .medium))
                    }
                } else if isRunning {
                    Text("What do you want to focus on?")
                        .font(.system(size: 15))
                        .foregroundStyle(.secondary)
                } else {
                    Text("Ready to focus")
                        .font(.system(size: 15))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.top, 6)

            Spacer().frame(height: 28)

            // ── Main content area ──

            if !isRunning {
                // Backend still starting up (auto-launched by the app itself).
                ProgressView()
                    .padding(.top, 20)
                Text("Starting up…")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .padding(.top, 14)

            } else if let s = session {
                // Session active → show end button
                VStack(spacing: 6) {
                    Text(s.title)
                        .font(.system(size: 16, weight: .semibold))
                    Text(s.class_name + " · " + s.event_type)
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                }
                .padding(.bottom, 20)

                Button(action: endSession) {
                    HStack(spacing: 10) {
                        Image(systemName: "stop.fill")
                        Text("End Session")
                    }
                }
                .buttonStyle(PrimaryButtonStyle(wide: true))

            } else {
                // Backend running, no session → show task picker
                VStack(spacing: 22) {
                    customTaskCard

                    if config.notionEnabled && !events.isEmpty {
                        HStack {
                            Rectangle().fill(Theme.border).frame(height: 1)
                            Text("OR")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.secondary)
                                .tracking(1.0)
                            Rectangle().fill(Theme.border).frame(height: 1)
                        }
                        .padding(.vertical, 2)

                        notionSection
                    }
                }
                .frame(maxWidth: 460)
                .padding(.horizontal, 32)

            }

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear(perform: startPolling)
        .onDisappear(perform: stopPolling)
    }

    // MARK: – Custom task

    private var customTaskCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("WHAT ARE YOU WORKING ON?")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .tracking(0.5)

            TextField("e.g. Write essay intro", text: $customTask)
                .textFieldStyle(.roundedBorder)
                .font(.system(size: 14))
                .onSubmit(startCustomSession)

            Button(action: startCustomSession) {
                HStack(spacing: 10) {
                    Image(systemName: "play.fill")
                    Text("Start Session")
                }
            }
            .buttonStyle(PrimaryButtonStyle(wide: true))
            .disabled(customTask.trimmingCharacters(in: .whitespaces).isEmpty)
            .opacity(customTask.trimmingCharacters(in: .whitespaces).isEmpty ? 0.5 : 1)
            .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    // MARK: – Schedule section

    private var notionSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("UPCOMING")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .tracking(0.5)
                Spacer()
            }
            eventList

            if selectedIndex != nil {
                Button(action: startSession) {
                    HStack(spacing: 10) {
                        Image(systemName: "play.fill")
                        Text("Start Session")
                    }
                }
                .buttonStyle(PrimaryButtonStyle(wide: true))
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
    }

    // MARK: – Event list

    private var eventList: some View {
        // Compute per-row whether to show a date header by comparing to the
        // previous event's date. Deriving this from `events` directly avoids
        // the non-reactive `var lastDate` side-effect that could mis-render
        // when SwiftUI re-evaluates the ForEach out of order.
        ScrollView {
            VStack(spacing: 5) {
                let indexed = Array(events.enumerated())
                ForEach(indexed, id: \.element.id) { idx, ev in
                    let prevDate: String = idx > 0 ? events[idx - 1].date : ""
                    let showHeader = ev.date != prevDate

                    if showHeader {
                        HStack {
                            Text(dateLabel(ev.date))
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(.secondary)
                                .textCase(.uppercase)
                            Spacer()
                        }
                        .padding(.top, idx == 0 ? 0 : 10)
                        .padding(.bottom, 2)
                    }

                    eventRow(ev, index: idx)
                }
            }
        }
        .frame(maxHeight: 200)
    }

    private func eventRow(_ ev: BackendEvent, index: Int) -> some View {
        let sel = selectedIndex == index
        let icon: String = {
            if ev.source == "ical" { return "calendar" }
            return ev.event_type == "Exam" ? "doc.text.magnifyingglass" : "doc.text"
        }()
        let subtitle: String = {
            var parts: [String] = []
            if let t = ev.start_time, !t.isEmpty { parts.append(formatTime(t)) }
            if !ev.class_name.isEmpty { parts.append(ev.class_name) }
            return parts.joined(separator: " · ")
        }()

        return Button(action: { selectedIndex = index }) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 13))
                    .foregroundStyle(sel ? Theme.accent : .secondary)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 2) {
                    Text(ev.title)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    if !subtitle.isEmpty {
                        Text(subtitle)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if sel {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 15))
                        .foregroundStyle(Theme.accent)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(sel ? Theme.accentMuted : Theme.card)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(sel ? Theme.accent.opacity(0.4) : Theme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    /// Convert "HH:MM" (24h) to "h:mm a" for display.
    private func formatTime(_ t: String) -> String {
        let inFmt = DateFormatter(); inFmt.dateFormat = "HH:mm"
        guard let d = inFmt.date(from: t) else { return t }
        let outFmt = DateFormatter(); outFmt.dateFormat = "h:mm a"
        return outFmt.string(from: d)
    }

    private func dateLabel(_ dateStr: String) -> String {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        guard let d = fmt.date(from: dateStr) else { return dateStr }
        if Calendar.current.isDateInToday(d) { return "Today" }
        if Calendar.current.isDateInTomorrow(d) { return "Tomorrow" }
        let display = DateFormatter()
        display.dateFormat = "EEE MMM d"
        return display.string(from: d)
    }

    // MARK: – Actions

    private func startSession() {
        guard let idx = selectedIndex, idx < events.count else { return }
        let ev = events[idx]
        // Send a stable handle — index alone races with Notion refresh.
        sendCommand(type: "start_session", data: [
            "event_index": idx,
            "title": ev.title,
            "date": ev.date,
        ])
        selectedIndex = nil
    }

    private func startCustomSession() {
        let trimmed = customTask.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        sendCommand(type: "start_custom_session", data: ["title": trimmed])
        customTask = ""
    }

    private func endSession() {
        sendCommand(type: "end_session")
    }

    // MARK: – State / commands

    private func readState() {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: statePath)),
              let state = try? JSONDecoder().decode(BackendState.self, from: data) else {
            return
        }
        let fresh = (Date().timeIntervalSince1970 - state.updated_at) < 120
        DispatchQueue.main.async {
            isRunning = fresh
            events = state.events
            session = state.session
        }
    }

    private func sendCommand(type: String, data: [String: Any] = [:]) {
        let cmd: [String: Any] = ["type": type, "data": data]
        guard let json = try? JSONSerialization.data(withJSONObject: cmd) else { return }
        // Atomic write — replaces any existing file at commandPath
        try? json.write(to: URL(fileURLWithPath: commandPath), options: .atomic)
    }

    private func startPolling() {
        readState()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { _ in
            readState()
        }
    }

    private func stopPolling() {
        pollTimer?.invalidate()
        pollTimer = nil
    }
}
