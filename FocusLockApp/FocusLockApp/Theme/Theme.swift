import SwiftUI
import AppKit

enum Theme {
    // Palette mirrors the marketing site (docs/style.css).
    // Light: cream / surface / ink. Dark: muted variants.
    static let accent       = Color(red: 0.910, green: 0.627, blue: 0.125)   // #E8A020 gold
    static let accentMuted  = Color(red: 0.992, green: 0.953, blue: 0.878)   // #FDF3E0 gold-pale

    static var surface: Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            if appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua {
                return NSColor(red: 0.082, green: 0.066, blue: 0.039, alpha: 1.0)
            }
            return NSColor(red: 0.992, green: 0.980, blue: 0.961, alpha: 1.0)   // #FDFAF5 cream
        })
    }

    static var card: Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            if appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua {
                return NSColor(red: 0.13, green: 0.11, blue: 0.07, alpha: 1.0)
            }
            return NSColor(red: 0.969, green: 0.949, blue: 0.910, alpha: 1.0)   // #F7F2E8 surface
        })
    }

    static var border: Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            if appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua {
                return NSColor.white.withAlphaComponent(0.09)
            }
            return NSColor(red: 0.910, green: 0.875, blue: 0.784, alpha: 1.0)   // #E8DFC8 border
        })
    }
}

// Custom-font shortcuts. Fonts are bundled in Resources/Fonts/ and registered
// via ATSApplicationFontsPath in Info.plist.
extension Font {
    static func serif(_ size: CGFloat) -> Font {
        .custom("InstrumentSerif-Regular", size: size)
    }
    static func mono(_ size: CGFloat, medium: Bool = false) -> Font {
        .custom(medium ? "DMMono-Medium" : "DMMono-Regular", size: size)
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    var wide: Bool = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(Color.black.opacity(0.85))
            .padding(.horizontal, wide ? 40 : 20)
            .padding(.vertical, wide ? 14 : 9)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: wide ? 12 : 8)
                    .fill(Theme.accent.opacity(configuration.isPressed ? 0.75 : 1.0))
            )
            .scaleEffect(configuration.isPressed ? 0.98 : 1.0)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(.primary)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Theme.border, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.6 : 1.0)
    }
}
