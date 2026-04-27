import SwiftUI
import AppKit

// First-run flow. Triggers the real macOS permission prompts and lets the
// user verify each one before they hit a dialog mid-session.
//
// Locus needs:
//   • Automation → Google Chrome    (read/control tabs for URL blocking)
//   • Automation → System Events    (force-quit distracting apps)
//
// We detect the Chrome one by executing a harmless AppleScript ("tell
// chrome to count windows"). On first call macOS shows the system dialog;
// on subsequent denies it errors out and we point the user at Settings.

enum PermissionStatus {
    case unknown, granted, denied
}

struct OnboardingView: View {
    @AppStorage("hasCompletedOnboarding") private var done = false
    @State private var step = 0
    @State private var chromeStatus: PermissionStatus = .unknown
    @State private var systemEventsStatus: PermissionStatus = .unknown

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(40)
            Divider()
            footer
        }
        .frame(width: 560, height: 440)
    }

    // ── Header ──────────────────────────────────────────────────────────

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: "lock.fill")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Theme.accent)
            Text("Welcome to Locus")
                .font(.system(size: 15, weight: .semibold))
            Spacer()
            Text("\(step + 1) / 3")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    // ── Step content ───────────────────────────────────────────────────

    @ViewBuilder
    private var content: some View {
        switch step {
        case 0: welcomeStep
        case 1: chromeStep
        default: systemEventsStep
        }
    }

    private var welcomeStep: some View {
        VStack(spacing: 18) {
            Image(systemName: "sparkles")
                .font(.system(size: 44))
                .foregroundStyle(Theme.accent)
            Text("Lock in. Get to work.")
                .font(.serif(32))
            Text("Locus needs two macOS permissions to block distracting apps and websites during a focus session. We'll walk through them now — takes under a minute.")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: 420)
    }

    private var chromeStep: some View {
        PermissionStep(
            icon: "globe",
            title: "Allow control of Google Chrome",
            detail: "Locus watches the active Chrome tab so it can block distracting sites. macOS will show a system dialog — click OK.",
            status: chromeStatus,
            action: triggerChromePermission,
            openSettings: openAutomationSettings,
            ctaText: chromeStatus == .denied ? "Open System Settings" : "Request Access"
        )
    }

    private var systemEventsStep: some View {
        PermissionStep(
            icon: "power",
            title: "Allow control of System Events",
            detail: "Locus uses System Events to force-quit distracting apps when a session starts.",
            status: systemEventsStatus,
            action: triggerSystemEventsPermission,
            openSettings: openAutomationSettings,
            ctaText: systemEventsStatus == .denied ? "Open System Settings" : "Request Access"
        )
    }

    // ── Footer ──────────────────────────────────────────────────────────

    private var footer: some View {
        HStack {
            if step > 0 {
                Button("Back") { step -= 1 }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button(step < 2 ? "Continue" : "Finish") {
                if step < 2 { step += 1 } else { done = true }
            }
            .buttonStyle(PrimaryButtonStyle())
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    // ── Permission probes ──────────────────────────────────────────────

    private func triggerChromePermission() {
        let ok = runAppleScript("""
            tell application "Google Chrome"
                if it is running then
                    count windows
                else
                    return 0
                end if
            end tell
        """)
        chromeStatus = ok ? .granted : .denied
        if ok { advanceAfterGrant() }
    }

    private func triggerSystemEventsPermission() {
        let ok = runAppleScript("""
            tell application "System Events"
                name of first process
            end tell
        """)
        systemEventsStatus = ok ? .granted : .denied
        if ok { advanceAfterGrant() }
    }

    /// Once a permission is granted, give the user a beat to see the green
    /// "Granted" badge, then advance — saves a click per step.
    private func advanceAfterGrant() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) {
            if step < 2 { step += 1 } else { done = true }
        }
    }

    private func openAutomationSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation") {
            NSWorkspace.shared.open(url)
        }
    }

    @discardableResult
    private func runAppleScript(_ src: String) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        p.arguments = ["-e", src]
        let errPipe = Pipe()
        p.standardError = errPipe
        p.standardOutput = Pipe()
        do {
            try p.run()
            p.waitUntilExit()
        } catch {
            return false
        }
        return p.terminationStatus == 0
    }
}

private struct PermissionStep: View {
    let icon: String
    let title: String
    let detail: String
    let status: PermissionStatus
    let action: () -> Void
    let openSettings: () -> Void
    let ctaText: String

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: icon)
                .font(.system(size: 36))
                .foregroundStyle(Theme.accent)
            Text(title)
                .font(.serif(22))
                .multilineTextAlignment(.center)
            Text(detail)
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 420)
            statusBadge
            Button(action: {
                if status == .denied {
                    openSettings()
                } else {
                    action()
                }
            }) {
                Text(ctaText)
            }
            .buttonStyle(PrimaryButtonStyle())
        }
    }

    @ViewBuilder
    private var statusBadge: some View {
        switch status {
        case .unknown:
            EmptyView()
        case .granted:
            Label("Granted", systemImage: "checkmark.circle.fill")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.green)
        case .denied:
            Label("Denied — enable it manually in System Settings → Privacy & Security → Automation.", systemImage: "exclamationmark.triangle.fill")
                .font(.system(size: 12))
                .foregroundStyle(.orange)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 420)
        }
    }
}
