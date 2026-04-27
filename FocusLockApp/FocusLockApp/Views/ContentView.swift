import SwiftUI

enum Pane: String, CaseIterable, Identifiable {
    case launcher = "Start"
    case settings = "Settings"
    case connectors = "Connectors"
    case analytics = "Analytics"

    var id: String { rawValue }
    var icon: String {
        switch self {
        case .launcher: return "play.fill"
        case .settings: return "gearshape.fill"
        case .connectors: return "bolt.horizontal.fill"
        case .analytics: return "chart.bar.fill"
        }
    }
}

struct ContentView: View {
    @State private var selection: Pane = .launcher
    @AppStorage("hasCompletedOnboarding") private var hasCompletedOnboarding = false

    var body: some View {
        NavigationSplitView {
            Sidebar(selection: $selection)
                .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 240)
        } detail: {
            Group {
                switch selection {
                case .launcher: LauncherView()
                case .settings: GeneralSettingsView()
                case .connectors: ConnectorsView()
                case .analytics: AnalyticsView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Theme.surface)
        }
        .sheet(isPresented: .constant(!hasCompletedOnboarding)) {
            OnboardingView()
                .interactiveDismissDisabled()
        }
    }
}

private struct Sidebar: View {
    @Binding var selection: Pane

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "lock.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Theme.accent)
                Text("Locus")
                    .font(.serif(22))
                Spacer()
            }
            .padding(.horizontal, 18)
            .padding(.top, 22)
            .padding(.bottom, 18)

            ForEach(Pane.allCases) { pane in
                SidebarRow(pane: pane, selected: selection == pane) {
                    selection = pane
                }
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface)
    }
}

private struct SidebarRow: View {
    let pane: Pane
    let selected: Bool
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 12) {
                Image(systemName: pane.icon)
                    .font(.system(size: 13, weight: .medium))
                    .frame(width: 18)
                    .foregroundStyle(selected ? Theme.accent : .secondary)
                Text(pane.rawValue)
                    .font(.system(size: 14, weight: selected ? .semibold : .regular))
                    .foregroundStyle(.primary)
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(selected ? Theme.accentMuted : Color.clear)
            )
            .padding(.horizontal, 10)
        }
        .buttonStyle(.plain)
    }
}
