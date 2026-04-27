import SwiftUI
import Charts

// MARK: - Codable model for /tmp/focuslock_analytics.json

private struct AnalyticsSummary: Codable {
    let generated_at: Double
    let focus_today: Int
    let focus_week: Int
    let focus_all: Int
    let sessions_today: Int
    let sessions_week: Int
    let sessions_all: Int
    let avg_session_seconds: Int
    let streak_days: Int
    let app_focus_today: [[PairElement]]
    let app_focus_week: [[PairElement]]
    let app_focus_all: [[PairElement]]
    let domain_visits: [[PairElement]]
    let impulse_blocks: [[PairElement]]
    let block_approved: Int
    let block_denied: Int
    let block_canceled: Int
    let off_topic_all: Int
    let session_histogram: [String: Int]
    let daily_focus_series: [String: Int]
    let hour_of_day: [String: Int]
    let off_topic_series: [String: Int]
}

// Heterogeneous element in Python [name, count] pairs.
// Each element is either a String (name) or an Int/Double (count).
private enum PairElement: Codable {
    case string(String)
    case int(Int)
    case double(Double)

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) { self = .string(s); return }
        if let i = try? c.decode(Int.self)    { self = .int(i);    return }
        if let d = try? c.decode(Double.self) { self = .double(d); return }
        self = .string("")
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .int(let i):    try c.encode(i)
        case .double(let d): try c.encode(d)
        }
    }

    var asString: String? { if case .string(let s) = self { return s }; return nil }
    var asInt: Int?    { if case .int(let i)    = self { return i }; return nil }
    var asDouble: Double? {
        switch self {
        case .double(let d): return d
        case .int(let i):    return Double(i)
        default:             return nil
        }
    }
}

// Convenience helpers to unpack [[name, count]] lists
private func pairs(_ raw: [[PairElement]]) -> [(String, Int)] {
    raw.compactMap { arr in
        guard arr.count >= 2,
              let name  = arr[0].asString,
              let count = arr[1].asInt else { return nil }
        return (name, count)
    }
}

private func pairsDouble(_ raw: [[PairElement]]) -> [(String, Double)] {
    raw.compactMap { arr in
        guard arr.count >= 2,
              let name  = arr[0].asString,
              let count = arr[1].asDouble else { return nil }
        return (name, count)
    }
}

// MARK: - Chart row models

private struct NamedValue: Identifiable {
    let name: String
    let value: Double
    var id: String { name }
}

private struct DaySeries: Identifiable {
    let date: String
    let value: Double
    var id: String { date }
}

private struct HourBucket: Identifiable {
    let hour: Int
    let count: Int
    var id: Int { hour }
    var label: String { "\(hour)" }
}

private struct HistoBucket: Identifiable {
    let label: String
    let count: Int
    var id: String { label }
}

private struct OutcomeSlice: Identifiable {
    let label: String
    let count: Int
    var id: String { label }
}

// MARK: - View

struct AnalyticsView: View {
    @State private var summary: AnalyticsSummary? = nil
    @State private var loadError: Bool = false
    @State private var pollTimer: Timer?

    private var analyticsPath: String { LocusPaths.analytics }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                Header(title: "Analytics", subtitle: "Your focus activity and blocking patterns.")

                if loadError {
                    errorBanner
                } else if summary == nil || isEmptySummary(summary!) {
                    emptyState
                } else {
                    let s = summary!
                    kpiRow(s)
                    dailyFocusChart(s)
                    hourOfDayChart(s)
                    appScreenTimeChart(s)
                    domainVisitsChart(s)
                    impulseLeaderboard(s)
                    blockOutcomesChart(s)
                    sessionHistogram(s)
                    offTopicChart(s)
                    allTimeTotals(s)
                }
            }
            .padding(32)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .onAppear(perform: startPolling)
        .onDisappear(perform: stopPolling)
    }

    // MARK: - Error / empty

    private var errorBanner: some View {
        Card {
            HStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
                Text("Could not read analytics data. Start a session to begin tracking.")
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
            }
        }
    }

    // Treat a fully-zero analytics file as "no data yet" — the backend writes
    // zeros on first run before any events exist, and we'd rather show the
    // empty state than a wall of empty charts.
    private func isEmptySummary(_ s: AnalyticsSummary) -> Bool {
        return s.sessions_all == 0 && s.focus_all == 0
            && s.block_approved == 0 && s.block_denied == 0
            && s.block_canceled == 0 && s.off_topic_all == 0
            && s.domain_visits.isEmpty && s.app_focus_all.isEmpty
    }

    private var emptyState: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                Text("No analytics yet")
                    .font(.system(size: 15, weight: .semibold))
                Text("Complete a focus session to see your analytics here. Data is written every 30 seconds while the backend is running.")
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - KPI row

    private func kpiRow(_ s: AnalyticsSummary) -> some View {
        HStack(spacing: 14) {
            KPICard(label: "Focus Today",
                    value: formatSeconds(s.focus_today),
                    sub: "today")
            KPICard(label: "Sessions Today",
                    value: "\(s.sessions_today)",
                    sub: "today")
            KPICard(label: "Streak",
                    value: "\(s.streak_days)d",
                    sub: "consecutive days")
            KPICard(label: "Blocks Denied",
                    value: "\(s.block_denied + s.block_canceled)",
                    sub: "all-time")
        }
    }

    // MARK: - Daily focus bar chart (14 days)

    private func dailyFocusChart(_ s: AnalyticsSummary) -> some View {
        let sorted = s.daily_focus_series
            .sorted { $0.key < $1.key }
            .map { DaySeries(date: shortDate($0.key), value: Double($0.value) / 60.0) }
        let hasData = sorted.contains { $0.value > 0 }

        return Card {
            VStack(alignment: .leading, spacing: 16) {
                FieldLabel("Daily Focus Time — Last 14 Days")
                if !hasData {
                    noDataLabel
                } else {
                    Chart(sorted) { b in
                        BarMark(
                            x: .value("Date", b.date),
                            y: .value("Minutes", b.value)
                        )
                        .foregroundStyle(Theme.accent)
                        .cornerRadius(3)
                    }
                    .chartYAxis {
                        AxisMarks(position: .leading) { v in
                            AxisGridLine()
                            AxisValueLabel {
                                if let n = v.as(Double.self) {
                                    Text("\(Int(n))m").font(.system(size: 10)).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    .chartXAxis {
                        AxisMarks(values: .stride(by: 2)) { v in
                            AxisValueLabel {
                                if let s = v.as(String.self) {
                                    Text(s).font(.system(size: 9)).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    .frame(height: 160)
                }
            }
        }
    }

    // MARK: - Hour of day

    private func hourOfDayChart(_ s: AnalyticsSummary) -> some View {
        let buckets = (0..<24).map { h -> HourBucket in
            let count = s.hour_of_day["\(h)"] ?? 0
            return HourBucket(hour: h, count: count)
        }
        let hasData = buckets.contains { $0.count > 0 }

        return Card {
            VStack(alignment: .leading, spacing: 16) {
                FieldLabel("Session Starts by Hour of Day")
                if !hasData {
                    noDataLabel
                } else {
                    Chart(buckets) { b in
                        BarMark(
                            x: .value("Hour", b.label),
                            y: .value("Sessions", b.count)
                        )
                        .foregroundStyle(Theme.accent.opacity(0.75))
                        .cornerRadius(2)
                    }
                    .chartXAxis {
                        AxisMarks(values: .stride(by: 4)) { v in
                            AxisValueLabel {
                                if let s = v.as(String.self), let h = Int(s) {
                                    Text(hourLabel(h)).font(.system(size: 9)).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    .chartYAxis {
                        AxisMarks(position: .leading) { v in
                            AxisGridLine()
                            AxisValueLabel {
                                if let n = v.as(Int.self) {
                                    Text("\(n)").font(.system(size: 10)).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    .frame(height: 120)
                }
            }
        }
    }

    // MARK: - App screen time (horizontal bar)

    private func appScreenTimeChart(_ s: AnalyticsSummary) -> some View {
        let rows = pairsDouble(s.app_focus_all)
            .prefix(10)
            .map { NamedValue(name: $0.0, value: $0.1 / 60.0) }
        return horizontalBarCard(
            label: "Top Apps by Screen Time (In-Session)",
            rows: Array(rows),
            formatValue: { formatSeconds(Int($0 * 60)) }
        )
    }

    // MARK: - Domain visits (horizontal bar)

    private func domainVisitsChart(_ s: AnalyticsSummary) -> some View {
        let rows = pairs(s.domain_visits)
            .prefix(10)
            .map { NamedValue(name: $0.0, value: Double($0.1)) }
        return horizontalBarCard(
            label: "Top Domains Visited During Sessions",
            rows: Array(rows),
            formatValue: { "\(Int($0))" }
        )
    }

    // MARK: - Impulse leaderboard (red)

    private func impulseLeaderboard(_ s: AnalyticsSummary) -> some View {
        let rows = pairs(s.impulse_blocks)
            .prefix(10)
            .map { NamedValue(name: $0.0, value: Double($0.1)) }
        return horizontalBarCard(
            label: "Impulse Leaderboard — blocks you couldn't justify",
            rows: Array(rows),
            formatValue: { "\(Int($0))" },
            barColor: .red
        )
    }

    // MARK: - Block outcomes donut

    private func blockOutcomesChart(_ s: AnalyticsSummary) -> some View {
        let slices = [
            OutcomeSlice(label: "Approved", count: s.block_approved),
            OutcomeSlice(label: "Denied", count: s.block_denied),
            OutcomeSlice(label: "Canceled", count: s.block_canceled),
        ].filter { $0.count > 0 }

        let total = s.block_approved + s.block_denied + s.block_canceled

        return Card {
            VStack(alignment: .leading, spacing: 16) {
                FieldLabel("Block Outcomes")
                if total == 0 {
                    noDataLabel
                } else {
                    HStack(alignment: .top, spacing: 24) {
                        GeometryReader { geo in
                            HStack(spacing: 2) {
                                ForEach(slices) { sl in
                                    outcomeColor(sl.label)
                                        .frame(width: max(2, geo.size.width * CGFloat(sl.count) / CGFloat(max(total, 1))))
                                }
                            }
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                        }
                        .frame(width: 180, height: 18)
                        .padding(.top, 6)

                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(slices) { sl in
                                HStack(spacing: 8) {
                                    outcomeColor(sl.label)
                                        .frame(width: 10, height: 10)
                                        .clipShape(Circle())
                                    Text(sl.label)
                                        .font(.system(size: 13))
                                    Spacer()
                                    Text("\(sl.count)")
                                        .font(.system(size: 13, weight: .semibold, design: .monospaced))
                                        .foregroundStyle(Theme.accent)
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    private func outcomeColor(_ label: String) -> Color {
        switch label {
        case "Approved": return Theme.accent
        case "Denied": return .red.opacity(0.8)
        default: return .secondary.opacity(0.5)
        }
    }

    // MARK: - Session length histogram

    private func sessionHistogram(_ s: AnalyticsSummary) -> some View {
        let order = ["0-15", "15-30", "30-60", "60-120", "120+"]
        let buckets = order.map { key -> HistoBucket in
            HistoBucket(label: key + "m", count: s.session_histogram[key] ?? 0)
        }
        let hasData = buckets.contains { $0.count > 0 }

        return Card {
            VStack(alignment: .leading, spacing: 16) {
                FieldLabel("Session Length Distribution")
                if !hasData {
                    noDataLabel
                } else {
                    Chart(buckets) { b in
                        BarMark(
                            x: .value("Length", b.label),
                            y: .value("Count", b.count)
                        )
                        .foregroundStyle(Theme.accent.opacity(0.8))
                        .cornerRadius(4)
                    }
                    .chartYAxis {
                        AxisMarks(position: .leading) { v in
                            AxisGridLine()
                            AxisValueLabel {
                                if let n = v.as(Int.self) {
                                    Text("\(n)").font(.system(size: 10)).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    .frame(height: 120)
                }
            }
        }
    }

    // MARK: - Off-topic detections over time

    private func offTopicChart(_ s: AnalyticsSummary) -> some View {
        let sorted = s.off_topic_series
            .sorted { $0.key < $1.key }
            .map { DaySeries(date: shortDate($0.key), value: Double($0.value)) }
        let hasData = sorted.contains { $0.value > 0 }

        return Card {
            VStack(alignment: .leading, spacing: 16) {
                FieldLabel("Off-Topic Detections — Last 14 Days")
                if !hasData {
                    Text("No off-topic detections recorded.")
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                } else {
                    Chart(sorted) { b in
                        LineMark(
                            x: .value("Date", b.date),
                            y: .value("Detections", b.value)
                        )
                        .foregroundStyle(Color.orange)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                        AreaMark(
                            x: .value("Date", b.date),
                            y: .value("Detections", b.value)
                        )
                        .foregroundStyle(Color.orange.opacity(0.15))
                    }
                    .chartYAxis {
                        AxisMarks(position: .leading) { v in
                            AxisGridLine()
                            AxisValueLabel {
                                if let n = v.as(Double.self) {
                                    Text("\(Int(n))").font(.system(size: 10)).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    .chartXAxis {
                        AxisMarks(values: .stride(by: 2)) { v in
                            AxisValueLabel {
                                if let s = v.as(String.self) {
                                    Text(s).font(.system(size: 9)).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    .frame(height: 120)
                }
            }
        }
    }

    // MARK: - All-time totals

    private func allTimeTotals(_ s: AnalyticsSummary) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                FieldLabel("All-Time Totals")
                HStack(spacing: 32) {
                    statBlock(label: "Focus Time", value: formatSeconds(s.focus_all))
                    statBlock(label: "Sessions", value: "\(s.sessions_all)")
                    statBlock(label: "Avg Session", value: formatSeconds(s.avg_session_seconds))
                    statBlock(label: "Blocks", value: "\(s.block_approved + s.block_denied + s.block_canceled)")
                    statBlock(label: "Off-Topic", value: "\(s.off_topic_all)")
                }
            }
        }
    }

    private func statBlock(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label)
                .font(.mono(10, medium: true))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
                .tracking(0.8)
            Text(value)
                .font(.serif(28))
                .foregroundStyle(Theme.accent)
        }
    }

    // MARK: - Reusable horizontal bar chart

    private func horizontalBarCard(
        label: String,
        rows: [NamedValue],
        formatValue: @escaping (Double) -> String,
        barColor: Color = Theme.accent
    ) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                FieldLabel(label)
                if rows.isEmpty {
                    noDataLabel
                } else {
                    let maxVal = rows.map(\.value).max() ?? 1
                    VStack(spacing: 0) {
                        ForEach(rows) { row in
                            horizontalBarRow(row, max: maxVal, format: formatValue, color: barColor)
                            if row.id != rows.last?.id {
                                Divider().opacity(0.12)
                            }
                        }
                    }
                }
            }
        }
    }

    private func horizontalBarRow(
        _ row: NamedValue,
        max maxVal: Double,
        format: (Double) -> String,
        color: Color
    ) -> some View {
        let fraction = maxVal > 0 ? row.value / maxVal : 0
        return HStack(spacing: 12) {
            Text(row.name)
                .font(.system(size: 12, weight: .medium))
                .lineLimit(1)
                .frame(width: 150, alignment: .leading)

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 3)
                        .fill(Theme.border)
                        .frame(height: 6)
                    RoundedRectangle(cornerRadius: 3)
                        .fill(color)
                        .frame(width: geo.size.width * fraction, height: 6)
                }
                .frame(maxHeight: .infinity, alignment: .center)
            }
            .frame(height: 20)

            Text(format(row.value))
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 60, alignment: .trailing)
        }
        .padding(.vertical, 8)
    }

    private var noDataLabel: some View {
        Text("No data recorded yet.")
            .font(.system(size: 13))
            .foregroundStyle(.secondary)
    }

    // MARK: - Formatting helpers

    private func formatSeconds(_ secs: Int) -> String {
        if secs <= 0 { return "0m" }
        let h = secs / 3600
        let m = (secs % 3600) / 60
        if h == 0 { return "\(m)m" }
        if m == 0 { return "\(h)h" }
        return "\(h)h \(m)m"
    }

    private func shortDate(_ iso: String) -> String {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        guard let d = fmt.date(from: iso) else { return iso }
        let out = DateFormatter()
        out.dateFormat = "M/d"
        return out.string(from: d)
    }

    private func hourLabel(_ h: Int) -> String {
        switch h {
        case 0: return "12a"
        case 12: return "12p"
        case let x where x < 12: return "\(x)a"
        default: return "\(h - 12)p"
        }
    }

    // MARK: - Polling

    private func loadAnalytics() {
        DispatchQueue.global(qos: .utility).async {
            guard let data = try? Data(contentsOf: URL(fileURLWithPath: analyticsPath)) else {
                DispatchQueue.main.async { loadError = false }
                return
            }
            guard let decoded = try? JSONDecoder().decode(AnalyticsSummary.self, from: data) else {
                DispatchQueue.main.async { loadError = true }
                return
            }
            DispatchQueue.main.async {
                summary = decoded
                loadError = false
            }
        }
    }

    private func startPolling() {
        loadAnalytics()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in
            loadAnalytics()
        }
    }

    private func stopPolling() {
        pollTimer?.invalidate()
        pollTimer = nil
    }
}

// MARK: - KPI card

private struct KPICard: View {
    let label: String
    let value: String
    let sub: String

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 4) {
                Text(label)
                    .font(.mono(11, medium: true))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                    .tracking(0.8)
                Text(value)
                    .font(.serif(32))
                    .foregroundStyle(Theme.accent)
                Text(sub)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
        }
    }
}
